"""Org and project membership helpers + resource access checks."""
from __future__ import annotations

import uuid
from typing import Any, Optional

from fastapi import HTTPException
from sqlalchemy import select

from app.core.db import (
    Organization,
    OrgMembership,
    Project,
    ProjectMembership,
    SessionLocal,
    User,
)
from app.core.rbac import has_min_role, normalize_role


def is_super_admin(user: dict[str, Any]) -> bool:
    return normalize_role(user.get("role")) == "super_admin"


def org_membership(user_id: str, org_id: str) -> Optional[OrgMembership]:
    with SessionLocal() as session:
        return session.scalar(
            select(OrgMembership).where(
                OrgMembership.org_id == org_id,
                OrgMembership.user_id == user_id,
            )
        )


def is_org_admin(user: dict[str, Any], org_id: str) -> bool:
    if is_super_admin(user):
        return True
    row = org_membership(str(user.get("id") or ""), org_id)
    return bool(row and row.org_role == "org_admin")


def user_org_ids(user_id: str) -> list[str]:
    with SessionLocal() as session:
        rows = session.scalars(
            select(OrgMembership.org_id).where(OrgMembership.user_id == user_id)
        ).all()
        return [str(r) for r in rows]


def list_org_members(org_id: str) -> list[dict[str, Any]]:
    with SessionLocal() as session:
        memberships = session.scalars(
            select(OrgMembership).where(OrgMembership.org_id == org_id)
        ).all()
        out: list[dict[str, Any]] = []
        for m in memberships:
            user = session.get(User, m.user_id)
            if user is None:
                continue
            out.append(
                {
                    "membership_id": m.id,
                    "org_id": m.org_id,
                    "org_role": m.org_role,
                    "user": {
                        "id": user.id,
                        "username": user.username,
                        "email": getattr(user, "email", "") or "",
                        "name": user.display_name,
                        "role": normalize_role(user.role),
                        "is_active": bool(user.is_active),
                    },
                }
            )
        return out


def ensure_org_membership(
    *,
    org_id: str,
    user_id: str,
    org_role: str = "member",
) -> dict[str, Any]:
    role = "org_admin" if org_role == "org_admin" else "member"
    with SessionLocal() as session:
        row = session.scalar(
            select(OrgMembership).where(
                OrgMembership.org_id == org_id,
                OrgMembership.user_id == user_id,
            )
        )
        if row is None:
            row = OrgMembership(
                id=str(uuid.uuid4()),
                org_id=org_id,
                user_id=user_id,
                org_role=role,
            )
            session.add(row)
        else:
            row.org_role = role
        session.commit()
        return {"id": row.id, "org_id": org_id, "user_id": user_id, "org_role": row.org_role}


def project_membership(user_id: str, project_id: str) -> Optional[ProjectMembership]:
    with SessionLocal() as session:
        return session.scalar(
            select(ProjectMembership).where(
                ProjectMembership.project_id == project_id,
                ProjectMembership.user_id == user_id,
            )
        )


def list_project_members(project_id: str) -> list[dict[str, Any]]:
    with SessionLocal() as session:
        memberships = session.scalars(
            select(ProjectMembership).where(ProjectMembership.project_id == project_id)
        ).all()
        out: list[dict[str, Any]] = []
        for m in memberships:
            user = session.get(User, m.user_id)
            if user is None:
                continue
            out.append(
                {
                    "membership_id": m.id,
                    "project_id": m.project_id,
                    "project_role": m.project_role,
                    "user": {
                        "id": user.id,
                        "username": user.username,
                        "email": getattr(user, "email", "") or "",
                        "name": user.display_name,
                        "role": normalize_role(user.role),
                        "is_active": bool(user.is_active),
                    },
                }
            )
        return out


def ensure_project_membership(
    *,
    project_id: str,
    user_id: str,
    project_role: str = "developer",
) -> dict[str, Any]:
    role = normalize_role(project_role)
    if role in {"super_admin", "org_admin"}:
        role = "devops_lead"
    with SessionLocal() as session:
        row = session.scalar(
            select(ProjectMembership).where(
                ProjectMembership.project_id == project_id,
                ProjectMembership.user_id == user_id,
            )
        )
        if row is None:
            row = ProjectMembership(
                id=str(uuid.uuid4()),
                project_id=project_id,
                user_id=user_id,
                project_role=role,
            )
            session.add(row)
        else:
            row.project_role = role
        session.commit()
        return {
            "id": row.id,
            "project_id": project_id,
            "user_id": user_id,
            "project_role": row.project_role,
        }


def remove_project_membership(*, project_id: str, user_id: str) -> bool:
    with SessionLocal() as session:
        row = session.scalar(
            select(ProjectMembership).where(
                ProjectMembership.project_id == project_id,
                ProjectMembership.user_id == user_id,
            )
        )
        if row is None:
            return False
        session.delete(row)
        session.commit()
        return True


def user_project_ids(user_id: str) -> list[str]:
    with SessionLocal() as session:
        return [
            str(r)
            for r in session.scalars(
                select(ProjectMembership.project_id).where(
                    ProjectMembership.user_id == user_id
                )
            ).all()
        ]


def project_org_id(project_id: str) -> Optional[str]:
    with SessionLocal() as session:
        project = session.get(Project, project_id)
        if project is None:
            return None
        return (project.org_id or "").strip() or None


def can_access_project(user: dict[str, Any], project_id: str) -> bool:
    if is_super_admin(user):
        return True
    user_id = str(user.get("id") or "")
    org_id = project_org_id(project_id)
    if org_id and is_org_admin(user, org_id):
        return True
    return project_membership(user_id, project_id) is not None


def assert_project_access(user: dict[str, Any], project_id: str) -> None:
    if not can_access_project(user, project_id):
        raise HTTPException(status_code=403, detail="No access to this project")


def assert_org_access(user: dict[str, Any], org_id: str) -> None:
    if is_super_admin(user):
        return
    if org_membership(str(user.get("id") or ""), org_id) is None:
        raise HTTPException(status_code=403, detail="No access to this organization")


def assert_org_admin(user: dict[str, Any], org_id: str) -> None:
    if not is_org_admin(user, org_id):
        raise HTTPException(status_code=403, detail="Org Admin required")


def effective_role_for_project(user: dict[str, Any], project_id: str) -> str:
    """Highest of global role, org_admin (as org_admin), and project_role."""
    global_role = normalize_role(user.get("role"))
    if global_role == "super_admin":
        return "super_admin"
    org_id = project_org_id(project_id)
    if org_id and is_org_admin(user, org_id):
        return "org_admin"
    membership = project_membership(str(user.get("id") or ""), project_id)
    if membership:
        return normalize_role(membership.project_role)
    return global_role


def can_manage_project_members_propose(user: dict[str, Any], project_id: str) -> bool:
    """DevOps Lead+ on the project (or org admin / super admin) can propose member changes."""
    role = effective_role_for_project(user, project_id)
    return has_min_role(role, "devops_lead")


def primary_org_id(user: dict[str, Any]) -> Optional[str]:
    """First org for the user (org memberships), preferring org_admin."""
    user_id = str(user.get("id") or "")
    if not user_id:
        return None
    with SessionLocal() as session:
        rows = session.scalars(
            select(OrgMembership).where(OrgMembership.user_id == user_id)
        ).all()
        if not rows:
            return None
        for row in rows:
            if row.org_role == "org_admin":
                return row.org_id
        return rows[0].org_id


def ensure_user_org(user: dict[str, Any]) -> str:
    """Return an org id for the user, creating a personal org when they have none.

    Invited users already have membership. Self-serve / legacy users hit onboarding
    without an org — provision one so project create does not fail.
    """
    existing = primary_org_id(user)
    if existing:
        return existing
    user_id = str(user.get("id") or "")
    if not user_id:
        raise ValueError("Not authenticated")
    from app.tenancy import orgs

    name = (user.get("name") or user.get("username") or "Personal").strip()
    org = orgs.create_org(
        name=f"{name}'s org",
        created_by=user_id,
        org_admin_user_id=user_id,
    )
    return str(org["id"])


def list_accessible_project_rows(user: dict[str, Any]) -> list[Project]:
    with SessionLocal() as session:
        if is_super_admin(user):
            return list(session.scalars(select(Project).order_by(Project.created_at.asc())).all())
        user_id = str(user.get("id") or "")
        org_ids = user_org_ids(user_id)
        admin_org_ids = [
            m.org_id
            for m in session.scalars(
                select(OrgMembership).where(
                    OrgMembership.user_id == user_id,
                    OrgMembership.org_role == "org_admin",
                )
            ).all()
        ]
        project_ids = set(user_project_ids(user_id))
        rows: list[Project] = []
        for project in session.scalars(select(Project).order_by(Project.created_at.asc())).all():
            if project.org_id in admin_org_ids:
                rows.append(project)
            elif project.id in project_ids:
                rows.append(project)
            elif is_super_admin(user):
                rows.append(project)
        # Deduplicate while preserving order
        seen: set[str] = set()
        unique: list[Project] = []
        for p in rows:
            if p.id in seen:
                continue
            seen.add(p.id)
            unique.append(p)
        _ = org_ids  # reserved for future org-scoped listing
        return unique


def enrich_user_public(user: dict[str, Any]) -> dict[str, Any]:
    """Attach org_ids / primary_org_id / org_role for JWT and /me responses."""
    user_id = str(user.get("id") or "")
    org_ids = user_org_ids(user_id) if user_id else []
    out = dict(user)
    out["org_ids"] = org_ids
    primary = primary_org_id(user)
    out["primary_org_id"] = primary
    org_role = None
    if primary and user_id:
        membership = org_membership(user_id, primary)
        if membership:
            org_role = membership.org_role
    out["org_role"] = org_role
    # Effective label for shell: Org Admin if they admin an org, else global role.
    from app.core.rbac import ROLE_LABELS, normalize_role

    global_role = normalize_role(out.get("role"))
    if global_role == "super_admin":
        out["role_label"] = ROLE_LABELS["super_admin"]
        out["display_role"] = "super_admin"
    elif org_role == "org_admin":
        out["role_label"] = "Org Admin"
        out["display_role"] = "org_admin"
    else:
        out["role_label"] = ROLE_LABELS.get(global_role, global_role)
        out["display_role"] = global_role
    with SessionLocal() as session:
        email = ""
        if user_id:
            row = session.get(User, user_id)
            if row is not None:
                email = getattr(row, "email", "") or ""
        out["email"] = email
    return out


def user_is_org_admin_anywhere(user: dict[str, Any]) -> bool:
    if is_super_admin(user):
        return True
    user_id = str(user.get("id") or "")
    if not user_id:
        return False
    with SessionLocal() as session:
        row = session.scalar(
            select(OrgMembership.id).where(
                OrgMembership.user_id == user_id,
                OrgMembership.org_role == "org_admin",
            ).limit(1)
        )
        return row is not None
