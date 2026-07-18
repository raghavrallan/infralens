"""Project store: workspaces that isolate connections, chats and mapped repos.

Each project has its own provider credentials (Azure / AWS / GitHub) and its own
set of allowed GitHub repositories, so work for one client/product never leaks
into another. Chats are scoped to a project too.
"""
import uuid
from typing import Any, Optional

from sqlalchemy import delete, select

from app.db import (
    DEFAULT_PROJECT_ID,
    Approval,
    Chat,
    Connection,
    EngineeringMemory,
    Finding,
    Message,
    Project,
    SessionLocal,
    Workflow,
    WorkflowRun,
)


def _summary(project: Project) -> dict[str, Any]:
    return {
        "id": project.id,
        "name": project.name,
        "repos": list(project.repos or []),
        "created_at": project.created_at.isoformat() if project.created_at else None,
        "updated_at": project.updated_at.isoformat() if project.updated_at else None,
    }


def ensure_default() -> str:
    """Guarantee a default project exists and return its id."""
    with SessionLocal() as session:
        project = session.get(Project, DEFAULT_PROJECT_ID)
        if project is None:
            session.add(Project(id=DEFAULT_PROJECT_ID, name="Default project", repos=[]))
            session.commit()
    return DEFAULT_PROJECT_ID


def list_projects() -> list[dict[str, Any]]:
    ensure_default()
    with SessionLocal() as session:
        rows = session.execute(select(Project).order_by(Project.created_at.asc())).scalars()
        return [_summary(p) for p in rows]


def create_project(name: str) -> dict[str, Any]:
    project_id = str(uuid.uuid4())
    clean = " ".join((name or "").strip().split()) or "New project"
    with SessionLocal() as session:
        project = Project(id=project_id, name=clean, repos=[])
        session.add(project)
        session.commit()
        return _summary(project)


def get_project(project_id: str) -> Optional[dict[str, Any]]:
    with SessionLocal() as session:
        project = session.get(Project, project_id)
        return _summary(project) if project else None


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
        return _summary(project)


def set_repos(project_id: str, repos: list[str]) -> Optional[dict[str, Any]]:
    cleaned = sorted({r.strip() for r in repos if r and r.strip()})
    with SessionLocal() as session:
        project = session.get(Project, project_id)
        if project is None:
            return None
        project.repos = cleaned
        session.commit()
        return _summary(project)


def get_repos(project_id: str) -> list[str]:
    with SessionLocal() as session:
        project = session.get(Project, project_id)
        return list(project.repos or []) if project else []


def delete_project(project_id: str) -> bool:
    """Delete a project and everything scoped to it. The default is never removed."""
    if project_id == DEFAULT_PROJECT_ID:
        return False
    with SessionLocal() as session:
        project = session.get(Project, project_id)
        if project is None:
            return False
        chat_ids = list(
            session.execute(
                select(Chat.id).where(Chat.project_id == project_id)
            ).scalars()
        )
        if chat_ids:
            session.execute(delete(Message).where(Message.chat_id.in_(chat_ids)))
            session.execute(delete(Chat).where(Chat.id.in_(chat_ids)))
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
