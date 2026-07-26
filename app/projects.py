"""Project store: workspaces that isolate connections, chats and mapped repos.

Each project has its own provider credentials (Azure / AWS / GitHub) and its own
set of allowed GitHub repositories, so work for one client/product never leaks
into another. Chats are scoped to a project too.
"""
import uuid
from typing import Any, Optional

from sqlalchemy import delete, select

from app.db import (
    AppConfig,
    DEFAULT_PROJECT_ID,
    DEFAULT_PROJECT_CONFIG_KEY,
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


def _summary(project: Project, default_id: str | None) -> dict[str, Any]:
    return {
        "id": project.id,
        "name": display_text(project.name),
        "is_default": project.id == default_id,
        "repos": list(project.repos or []),
        "created_at": project.created_at.isoformat() if project.created_at else None,
        "updated_at": project.updated_at.isoformat() if project.updated_at else None,
    }


def ensure_default() -> str:
    """Guarantee exactly one default project exists and return its id."""
    with SessionLocal() as session:
        selected_id = _default_id(session)
        selected = session.get(Project, selected_id) if selected_id else None
        if selected is None:
            selected = session.scalar(select(Project).order_by(Project.created_at.asc(), Project.id.asc()))
        if selected is None:
            selected = Project(id=DEFAULT_PROJECT_ID, name="Default project", repos=[])
            session.add(selected)
            session.flush()
        setting = session.get(AppConfig, DEFAULT_PROJECT_CONFIG_KEY)
        if setting is None:
            session.add(AppConfig(key=DEFAULT_PROJECT_CONFIG_KEY, value=selected.id))
        elif setting.value != selected.id:
            setting.value = selected.id
        session.commit()
        return selected.id


def list_projects() -> list[dict[str, Any]]:
    ensure_default()
    with SessionLocal() as session:
        default_id = _default_id(session)
        rows = session.execute(select(Project).order_by(Project.created_at.asc())).scalars()
        return [_summary(p, default_id) for p in rows]


def create_project(name: str) -> dict[str, Any]:
    project_id = str(uuid.uuid4())
    clean = " ".join((name or "").strip().split()) or "New project"
    with SessionLocal() as session:
        project = Project(id=project_id, name=clean, repos=[])
        session.add(project)
        session.commit()
        return _summary(project, _default_id(session))


def get_project(project_id: str) -> Optional[dict[str, Any]]:
    with SessionLocal() as session:
        project = session.get(Project, project_id)
        return _summary(project, _default_id(session)) if project else None


def rename_project(project_id: str, name: str) -> Optional[dict[str, Any]]:
    clean = " ".join((name or "").strip().split())
    if not clean:
        return get_project(project_id)
    with SessionLocal() as session:
        project = session.get(Project, project_id)
        if project is None:
            return None
        project.name = clean
        session.commit()
        return _summary(project, _default_id(session))


def set_repos(project_id: str, repos: list[str]) -> Optional[dict[str, Any]]:
    cleaned = sorted({r.strip() for r in repos if r and r.strip()})
    with SessionLocal() as session:
        project = session.get(Project, project_id)
        if project is None:
            return None
        project.repos = cleaned
        session.commit()
        return _summary(project, _default_id(session))


def get_repos(project_id: str) -> list[str]:
    with SessionLocal() as session:
        project = session.get(Project, project_id)
        return list(project.repos or []) if project else []


def set_default(project_id: str) -> Optional[dict[str, Any]]:
    """Make one existing project the sole default workspace."""
    with SessionLocal() as session:
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
    """
    with SessionLocal() as session:
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
            session.execute(delete(Message).where(Message.chat_id.in_(chat_ids)))
            session.execute(delete(Chat).where(Chat.id.in_(chat_ids)))

        action_ids = list(
            session.execute(
                select(ExecutionJob.id).where(ExecutionJob.project_id == project_id)
            ).scalars()
        )
        if action_ids:
            session.execute(
                delete(ExecutionEvent).where(ExecutionEvent.action_id.in_(action_ids))
            )
            session.execute(
                delete(ExecutionApproval).where(
                    ExecutionApproval.action_id.in_(action_ids)
                )
            )
            session.execute(
                delete(ExecutionJob).where(ExecutionJob.id.in_(action_ids))
            )

        session.execute(delete(Connection).where(Connection.project_id == project_id))
        session.execute(delete(Approval).where(Approval.project_id == project_id))
        session.execute(delete(Finding).where(Finding.project_id == project_id))
        session.execute(delete(WorkflowRun).where(WorkflowRun.project_id == project_id))
        session.execute(delete(Workflow).where(Workflow.project_id == project_id))
        session.execute(
            delete(EngineeringMemory).where(
                EngineeringMemory.project_id == project_id
            )
        )
        session.delete(project)
        session.commit()
        return True
