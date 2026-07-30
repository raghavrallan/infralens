"""Project store: workspaces that isolate connections, chats and mapped repos.

Each project has its own provider credentials (Azure / AWS / GitHub) and its own
set of allowed GitHub repositories, so work for one client/product never leaks
into another. Chats are scoped to a project too.
"""
import json
import uuid
from typing import Any, Optional

from sqlalchemy import delete, select, update
from sqlalchemy.exc import ProgrammingError

from app.db import (
    AppConfig,
    DEFAULT_PROJECT_ID,
    DEFAULT_PROJECT_CONFIG_KEY,
    DELETED_PROJECTS_CONFIG_KEY,
    Approval,
    Chat,
    Connection,
    EngineeringMemory,
    ExecutionApproval,
    ExecutionEvent,
    ExecutionJob,
    Finding,
    Message,
    Project,
    SessionLocal,
    Workflow,
    WorkflowRun,
)
from app.presentation import display_text


def _default_id(session: Any) -> str | None:
    setting = session.get(AppConfig, DEFAULT_PROJECT_CONFIG_KEY)
    return setting.value if setting and setting.value else None


def _deleted_ids(session: Any) -> set[str]:
    setting = session.get(AppConfig, DELETED_PROJECTS_CONFIG_KEY)
    if setting is None or not setting.value:
        return set()
    try:
        data = json.loads(setting.value)
    except (TypeError, ValueError, json.JSONDecodeError):
        return set()
    if not isinstance(data, list):
        return set()
    return {str(item) for item in data if item}


def _mark_deleted(session: Any, project_id: str) -> None:
    ids = _deleted_ids(session)
    ids.add(project_id)
    payload = json.dumps(sorted(ids))
    setting = session.get(AppConfig, DELETED_PROJECTS_CONFIG_KEY)
    if setting is None:
        session.add(AppConfig(key=DELETED_PROJECTS_CONFIG_KEY, value=payload))
    else:
        setting.value = payload


def _try_execute(session: Any, statement: Any) -> bool:
    """Run a statement; return False when the DB role lacks privilege."""
    try:
        with session.begin_nested():
            session.execute(statement)
        return True
    except ProgrammingError:
        return False


def _summary(project: Project, default_id: str | None) -> dict[str, Any]:
    return {
        "id": project.id,
        "name": display_text(project.name),
        "org_id": getattr(project, "org_id", "") or "",
        "is_default": project.id == default_id,
        "repos": list(project.repos or []),
        "created_at": project.created_at.isoformat() if project.created_at else None,
        "updated_at": project.updated_at.isoformat() if project.updated_at else None,
    }


def ensure_default() -> str:
    """Guarantee exactly one default project exists and return its id."""
    with SessionLocal() as session:
        deleted = _deleted_ids(session)
        selected_id = _default_id(session)
        selected = session.get(Project, selected_id) if selected_id else None
        if selected is None or selected.id in deleted:
            selected = None
            for candidate in session.scalars(
                select(Project).order_by(Project.created_at.asc(), Project.id.asc())
            ):
                if candidate.id not in deleted:
                    selected = candidate
                    break
        if selected is None:
            # Reuse the seeded id only when that row does not already exist
            # (including soft-deleted tombstones still present in projects).
            new_id = (
                DEFAULT_PROJECT_ID
                if session.get(Project, DEFAULT_PROJECT_ID) is None
                else str(uuid.uuid4())
            )
            selected = Project(id=new_id, name="Default project", repos=[])
            session.add(selected)
            session.flush()
        setting = session.get(AppConfig, DEFAULT_PROJECT_CONFIG_KEY)
        if setting is None:
            session.add(AppConfig(key=DEFAULT_PROJECT_CONFIG_KEY, value=selected.id))
        elif setting.value != selected.id:
            setting.value = selected.id
        session.commit()
        return selected.id


def list_projects(user: Optional[dict[str, Any]] = None) -> list[dict[str, Any]]:
    """List projects. When ``user`` is provided, only accessible projects are returned."""
    if user is None:
        ensure_default()
        with SessionLocal() as session:
            default_id = _default_id(session)
            deleted = _deleted_ids(session)
            rows = session.execute(select(Project).order_by(Project.created_at.asc())).scalars()
            return [_summary(p, default_id) for p in rows if p.id not in deleted]

    from app import memberships

    # Do not auto-create a shared default for scoped users — empty means onboard.
    with SessionLocal() as session:
        default_id = _default_id(session)
        deleted = _deleted_ids(session)
        accessible = memberships.list_accessible_project_rows(user)
        return [
            _summary(p, default_id)
            for p in accessible
            if p.id not in deleted
        ]


def create_project(
    name: str,
    *,
    org_id: Optional[str] = None,
    owner_user_id: Optional[str] = None,
    owner_project_role: str = "devops_lead",
    reuse_empty: bool = False,
) -> dict[str, Any]:
    clean = " ".join((name or "").strip().split()) or "New project"

    # Reuse the caller's empty onboarding project so PAT/OAuth does not spawn duplicates.
    if reuse_empty and owner_user_id:
        from app import memberships

        for existing in list_projects(user={"id": owner_user_id, "role": "developer"}):
            # Only reuse projects the user owns with no mapped repos yet.
            if existing.get("org_id") and org_id and existing.get("org_id") != org_id:
                continue
            if not (existing.get("repos") or []):
                if clean and clean != "Onboarding project" and clean != "New project":
                    renamed = rename_project(existing["id"], clean)
                    if renamed:
                        memberships.ensure_project_membership(
                            project_id=existing["id"],
                            user_id=owner_user_id,
                            project_role=owner_project_role,
                        )
                        return renamed
                memberships.ensure_project_membership(
                    project_id=existing["id"],
                    user_id=owner_user_id,
                    project_role=owner_project_role,
                )
                return existing

    project_id = str(uuid.uuid4())
    with SessionLocal() as session:
        if not org_id:
            from app.db import Organization

            org = session.scalar(select(Organization).order_by(Organization.created_at.asc()))
            org_id = org.id if org else ""
        project = Project(id=project_id, name=clean, repos=[], org_id=org_id or "")
        session.add(project)
        session.commit()
        summary = _summary(project, _default_id(session))
    if owner_user_id:
        from app import memberships

        memberships.ensure_project_membership(
            project_id=project_id,
            user_id=owner_user_id,
            project_role=owner_project_role,
        )
    return summary


def collapse_duplicate_empty_projects(
    *,
    user: dict[str, Any],
    keep_project_id: str,
    org_id: Optional[str] = None,
) -> int:
    """Delete empty sibling projects created during onboarding retries. Returns count removed."""
    removed = 0
    for project in list_projects(user=user):
        pid = project["id"]
        if pid == keep_project_id:
            continue
        if org_id and project.get("org_id") and project.get("org_id") != org_id:
            continue
        if project.get("repos"):
            continue
        # Only remove empty shells the user can access.
        if delete_project(pid):
            removed += 1
    return removed


def get_project(project_id: str) -> Optional[dict[str, Any]]:
    with SessionLocal() as session:
        if project_id in _deleted_ids(session):
            return None
        project = session.get(Project, project_id)
        return _summary(project, _default_id(session)) if project else None


def rename_project(project_id: str, name: str) -> Optional[dict[str, Any]]:
    clean = " ".join((name or "").strip().split())
    if not clean:
        return get_project(project_id)
    with SessionLocal() as session:
        if project_id in _deleted_ids(session):
            return None
        project = session.get(Project, project_id)
        if project is None:
            return None
        project.name = clean
        session.commit()
        return _summary(project, _default_id(session))


def set_repos(project_id: str, repos: list[str]) -> Optional[dict[str, Any]]:
    cleaned = sorted({r.strip() for r in repos if r and r.strip()})
    with SessionLocal() as session:
        if project_id in _deleted_ids(session):
            return None
        project = session.get(Project, project_id)
        if project is None:
            return None
        project.repos = cleaned
        session.commit()
        return _summary(project, _default_id(session))


def get_repos(project_id: str) -> list[str]:
    with SessionLocal() as session:
        if project_id in _deleted_ids(session):
            return []
        project = session.get(Project, project_id)
        return list(project.repos or []) if project else []


def set_default(project_id: str) -> Optional[dict[str, Any]]:
    """Make one existing project the sole default workspace."""
    with SessionLocal() as session:
        if project_id in _deleted_ids(session):
            return None
        project = session.get(Project, project_id)
        if project is None:
            return None
        setting = session.get(AppConfig, DEFAULT_PROJECT_CONFIG_KEY)
        if setting is None:
            session.add(AppConfig(key=DEFAULT_PROJECT_CONFIG_KEY, value=project_id))
        else:
            setting.value = project_id
        session.commit()
        return _summary(project, project_id)


def delete_project(project_id: str) -> bool:
    """Delete a project and everything scoped to it.

    The current default workspace cannot be deleted — make another project
    default first. The seeded id ``default`` is allowed to be deleted once it
    is no longer the default (e.g. after it was renamed to AEYE).

    On Azure Postgres the app role often has SELECT/INSERT/UPDATE but not
    DELETE on tables owned by ``root_admin``. In that case we purge what we can,
    scrub secrets, and soft-hide the project via ``app_config``.
    """
    with SessionLocal() as session:
        deleted = _deleted_ids(session)
        if project_id in deleted:
            return False
        project = session.get(Project, project_id)
        if project is None:
            return False
        if project_id == _default_id(session):
            return False

        chat_ids = list(
            session.execute(
                select(Chat.id).where(Chat.project_id == project_id)
            ).scalars()
        )
        if chat_ids:
            _try_execute(session, delete(Message).where(Message.chat_id.in_(chat_ids)))
            _try_execute(session, delete(Chat).where(Chat.id.in_(chat_ids)))

        action_ids = list(
            session.execute(
                select(ExecutionJob.id).where(ExecutionJob.project_id == project_id)
            ).scalars()
        )
        if action_ids:
            _try_execute(
                session,
                delete(ExecutionEvent).where(ExecutionEvent.action_id.in_(action_ids)),
            )
            _try_execute(
                session,
                delete(ExecutionApproval).where(
                    ExecutionApproval.action_id.in_(action_ids)
                ),
            )
            _try_execute(
                session, delete(ExecutionJob).where(ExecutionJob.id.in_(action_ids))
            )

        hard_ok = True
        for statement in (
            delete(Connection).where(Connection.project_id == project_id),
            delete(Approval).where(Approval.project_id == project_id),
            delete(Finding).where(Finding.project_id == project_id),
            delete(WorkflowRun).where(WorkflowRun.project_id == project_id),
            delete(Workflow).where(Workflow.project_id == project_id),
            delete(EngineeringMemory).where(
                EngineeringMemory.project_id == project_id
            ),
        ):
            if not _try_execute(session, statement):
                hard_ok = False

        if hard_ok:
            try:
                with session.begin_nested():
                    session.delete(project)
            except ProgrammingError:
                hard_ok = False

        if not hard_ok:
            # Scrub credentials and hide the row — app role cannot DELETE it.
            session.execute(
                update(Connection)
                .where(Connection.project_id == project_id)
                .values(fields={}, method="")
            )
            project.repos = []
            _mark_deleted(session, project_id)

        session.commit()
        return True
