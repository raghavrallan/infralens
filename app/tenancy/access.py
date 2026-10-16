"""Org isolation for Azure connections, subscriptions, and project visibility.

This is the Postgres port of infralens-live ``src/lib/access.js`` and the live
permission checks those assertions use. Suite RBAC stays in ``app/core/rbac.py``
until the session phase merges the two ladders. Live project roles are stored
as themselves; they are not passed through ``normalize_role``.
"""
from __future__ import annotations

import re
import uuid
from typing import Any, Optional

from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.core.db import (
    AuditLog,
    AzureConnection,
    Project,
    ProjectConnection,
    ProjectMembership,
    ProjectSubscription,
    SessionLocal,
    Subscription,
)
from app.platform.secret_box import decrypt, encrypt

_GUID = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
    re.IGNORECASE,
)
ORG_ROLES = ("org_owner", "org_admin", "member")
PROJECT_ROLES = ("project_admin", "billing_reader", "operator", "viewer")
_ORG_ONLY = frozenset({"connection.manage", "members.manage", "project.create"})
_PROJECT_PERMISSIONS = {
    "project_admin": ("project.read", "billing.read", "resources.read", "project.manage"),
    "billing_reader": ("project.read", "billing.read", "resources.read"),
    "operator": ("project.read", "resources.read"),
    "viewer": ("project.read", "billing.read", "resources.read"),
}


class AccessError(Exception):
    """Live access failure. ``status`` is the HTTP status the route should use."""

    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status = status


def is_guid(value: object) -> bool:
    return _GUID.fullmatch(str(value or "").strip()) is not None


def is_org_manager(role: Optional[str]) -> bool:
    return role in {"org_owner", "org_admin"}


def can(org_role: Optional[str], project_role: Optional[str], permission: str) -> bool:
    """Live permission check. An operator cannot read billing. A viewer can."""
    if permission in _ORG_ONLY:
        return is_org_manager(org_role)
    if is_org_manager(org_role):
        return True
    if not project_role:
        return False
    return permission in _PROJECT_PERMISSIONS.get(project_role, ())


def _budget(value: Any) -> Optional[float]:
    if value is None:
        return None
    return float(value)


def _project_view(project: Project, role: Optional[str]) -> dict[str, Any]:
    return {
        "id": project.id,
        "org_id": project.org_id,
        "name": project.name,
        "slug": project.slug,
        "budget_usd": _budget(project.budget_usd),
        "created_at": project.created_at,
        "role": role,
    }


def visible_projects(actor: dict[str, Any]) -> list[dict[str, Any]]:
    org_id = str(actor["org"]["id"])
    user_id = str(actor["user"]["id"])
    role = actor["membership"]["role"]
    with SessionLocal() as session:
        if is_org_manager(role):
            rows = session.scalars(
                select(Project).where(Project.org_id == org_id).order_by(Project.name.asc())
            ).all()
            return [_project_view(row, role) for row in rows]
        pairs = session.execute(
            select(Project, ProjectMembership.project_role)
            .join(ProjectMembership, ProjectMembership.project_id == Project.id)
            .where(Project.org_id == org_id, ProjectMembership.user_id == user_id)
            .order_by(Project.name.asc())
        ).all()
        return [_project_view(project, project_role) for project, project_role in pairs]


def require_project(actor: dict[str, Any], project_id: str, permission: str) -> dict[str, Any]:
    org_id = str(actor["org"]["id"])
    with SessionLocal() as session:
        project = session.get(Project, project_id)
        if project is None or project.org_id != org_id:
            raise AccessError(404, "Project not found.")
        project_role = session.scalar(
            select(ProjectMembership.project_role).where(
                ProjectMembership.project_id == project.id,
                ProjectMembership.user_id == str(actor["user"]["id"]),
            )
        )
        if not can(actor["membership"]["role"], project_role, permission):
            raise AccessError(403, "Your role does not allow that.")
        return _project_view(project, project_role)


def subscriptions_for_project(project_id: str, org_id: str) -> list[dict[str, Any]]:
    with SessionLocal() as session:
        rows = session.execute(
            select(
                Subscription.id,
                Subscription.name,
                Subscription.state,
                Subscription.connection_id,
            )
            .join(
                ProjectConnection,
                ProjectConnection.connection_id == Subscription.connection_id,
            )
            .join(Project, Project.id == ProjectConnection.project_id)
            .where(
                ProjectConnection.project_id == project_id,
                Project.org_id == org_id,
                Subscription.org_id == org_id,
            )
            .distinct()
        ).all()
    return [
        {
            "id": row.id,
            "name": row.name,
            "state": row.state,
            "connection_id": row.connection_id,
        }
        for row in rows
        if is_guid(row.id)
    ]


def _unique_ids(ids: Optional[list[Any]]) -> list[str]:
    unique: list[str] = []
    seen: set[str] = set()
    for item in ids or []:
        connection_id = str(item).strip()
        if not connection_id or connection_id in seen:
            continue
        seen.add(connection_id)
        unique.append(connection_id)
    return unique


def bind_connections(org_id: str, project_id: str, ids: Optional[list[Any]]) -> None:
    unique = _unique_ids(ids)
    with SessionLocal() as session:
        project = session.get(Project, project_id)
        if project is None or project.org_id != org_id:
            raise AccessError(404, "Project not found.")
        for connection_id in unique:
            row = session.get(AzureConnection, connection_id)
            if row is None or row.org_id != org_id:
                raise AccessError(400, "That connection is not on this organization.")
        session.execute(
            delete(ProjectConnection).where(ProjectConnection.project_id == project_id)
        )
        for connection_id in unique:
            session.add(
                ProjectConnection(project_id=project_id, connection_id=connection_id)
            )
        session.commit()


def bind_subscriptions(org_id: str, project_id: str, ids: Optional[list[Any]]) -> None:
    """Keep the legacy one-subscription-per-project table. The project API does not call this."""
    unique = _unique_ids(ids)
    with SessionLocal() as session:
        for sub_id in unique:
            if not is_guid(sub_id):
                raise AccessError(400, "Choose a real subscription.")
            sub = session.get(Subscription, sub_id)
            if sub is None or sub.org_id != org_id:
                raise AccessError(400, "That subscription is not on this organization.")
            taken = session.scalar(
                select(ProjectSubscription.project_id).where(
                    ProjectSubscription.subscription_id == sub_id
                )
            )
            if taken and taken != project_id:
                raise AccessError(409, "That subscription is already attached to another project.")
        session.execute(
            delete(ProjectSubscription).where(ProjectSubscription.project_id == project_id)
        )
        for sub_id in unique:
            session.add(ProjectSubscription(project_id=project_id, subscription_id=sub_id))
        session.commit()


def replace_subscriptions(org_id: str, connection_id: str, rows: list[dict[str, Any]]) -> None:
    clean: list[dict[str, str]] = []
    seen: set[str] = set()
    for row in rows or []:
        sub_id = str(row.get("id") or "").strip()
        if not is_guid(sub_id) or sub_id in seen:
            continue
        seen.add(sub_id)
        clean.append(
            {
                "id": sub_id,
                "name": str(row.get("name") or sub_id),
                "state": str(row.get("state") or ""),
            }
        )
    with SessionLocal() as session:
        for item in clean:
            owner = session.get(Subscription, item["id"])
            if owner is not None and owner.org_id != org_id:
                raise AccessError(
                    409,
                    "That subscription is already connected to another organization.",
                )
        for item in clean:
            stmt = pg_insert(Subscription).values(
                id=item["id"],
                org_id=org_id,
                connection_id=connection_id,
                name=item["name"],
                state=item["state"],
            )
            session.execute(
                stmt.on_conflict_do_update(
                    index_elements=["id"],
                    set_={
                        "name": stmt.excluded.name,
                        "state": stmt.excluded.state,
                        "connection_id": stmt.excluded.connection_id,
                        "org_id": stmt.excluded.org_id,
                    },
                )
            )
        existing = session.scalars(
            select(Subscription).where(
                Subscription.connection_id == connection_id,
                Subscription.org_id == org_id,
            )
        ).all()
        for row in existing:
            if row.id in seen:
                continue
            session.execute(
                delete(ProjectSubscription).where(
                    ProjectSubscription.subscription_id == row.id
                )
            )
            session.delete(row)
        session.commit()


def connection_secrets(connection_id: str, org_id: str) -> dict[str, str]:
    with SessionLocal() as session:
        row = session.get(AzureConnection, connection_id)
        if row is None or row.org_id != org_id:
            raise AccessError(404, "Azure connection not found.")
        return {
            "id": row.id,
            "tenant_id": row.tenant_id,
            "client_id": row.client_id,
            "client_secret": decrypt(row.secret_cipher),
        }


def public_azure_connection(row: AzureConnection) -> dict[str, Any]:
    client_id = row.client_id or ""
    return {
        "id": row.id,
        "org_id": row.org_id,
        "name": row.name,
        "status": row.status,
        "status_detail": row.status_detail or "",
        "client_hint": client_id[-4:],
        "last_checked_at": row.last_checked_at.isoformat() if row.last_checked_at else None,
    }


def save_azure_connection(
    *,
    org_id: str,
    name: str,
    tenant_id: str,
    client_id: str,
    client_secret: str,
) -> dict[str, Any]:
    """Store an app registration. Does not call Azure."""
    clean_name = " ".join((name or "").split())
    if len(clean_name) < 2:
        raise AccessError(400, "Name the connection.")
    if not is_guid(tenant_id) or not is_guid(client_id):
        raise AccessError(400, "Tenant ID and client ID must be Azure GUIDs.")
    if len(client_secret or "") < 8:
        raise AccessError(400, "Paste the client secret from the app registration.")
    normalized = client_id.strip().lower()
    tenant = tenant_id.strip().lower()
    cipher = encrypt(client_secret)
    with SessionLocal() as session:
        existing = session.scalar(
            select(AzureConnection).where(func.lower(AzureConnection.client_id) == normalized)
        )
        if existing is not None and existing.org_id != org_id:
            raise AccessError(409, "That client ID is already connected to another organization.")
        if existing is None:
            row = AzureConnection(
                id=uuid.uuid4().hex,
                org_id=org_id,
                name=clean_name[:120],
                tenant_id=tenant,
                client_id=normalized,
                secret_cipher=cipher,
                status="pending",
                status_detail="",
            )
            session.add(row)
        else:
            existing.name = clean_name[:120]
            existing.tenant_id = tenant
            existing.client_id = normalized
            existing.secret_cipher = cipher
            existing.status = "pending"
            existing.status_detail = ""
            row = existing
        session.commit()
        session.refresh(row)
        return public_azure_connection(row)


def merge_duplicate_azure_connections() -> int:
    """Keep the connected row for a client id, otherwise the latest, and delete the rest."""
    from app.core.db import merge_duplicate_azure_connections as merge_rows

    return merge_rows()


def audit(
    *,
    org_id: Optional[str] = None,
    project_id: Optional[str] = None,
    user_id: Optional[str] = None,
    action: str,
    detail: Optional[str] = None,
) -> str:
    row_id = uuid.uuid4().hex
    with SessionLocal() as session:
        session.add(
            AuditLog(
                id=row_id,
                org_id=org_id or None,
                project_id=project_id or None,
                user_id=user_id or None,
                action=action,
                detail=detail or None,
            )
        )
        session.commit()
    return row_id
