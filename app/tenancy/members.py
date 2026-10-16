"""Live organization member create.

An organization owner or admin can add a member or another org admin. A member
needs a project and a live project role. ``org_owner`` is not assigned here.
New people are stored with the suite password hash and a global ``viewer`` role
so the live project role is not widened by ``normalize_role``.
"""
from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import func, select

from app.core import auth
from app.core.db import OrgMembership, Project, ProjectMembership, SessionLocal, User
from app.tenancy.access import ORG_ROLES, PROJECT_ROLES, AccessError, audit, is_org_manager


def _username_for(session: Any, email: str) -> str:
    base = email if len(email) <= 64 else f"user-{uuid.uuid4().hex[:16]}"
    candidate = base
    n = 2
    while session.scalar(select(User.id).where(User.username == candidate)):
        suffix = f"-{n}"
        candidate = f"{base[:64 - len(suffix)]}{suffix}"
        n += 1
    return candidate


def add_org_member(
    actor: dict[str, Any],
    *,
    name: str,
    email: str,
    password: str,
    org_role: str,
    project_id: str = "",
    project_role: str = "",
) -> dict[str, Any]:
    if not is_org_manager(actor["membership"]["role"]):
        raise AccessError(403, "Only an organization admin can add members.")
    clean_email = (email or "").strip().lower()
    clean_role = (org_role or "member").strip()
    if "@" not in clean_email:
        raise AccessError(400, "Enter a valid email.")
    if clean_role not in ORG_ROLES or clean_role == "org_owner":
        raise AccessError(400, "Choose organization admin or member.")
    org_id = str(actor["org"]["id"])
    with SessionLocal() as session:
        if clean_role == "member":
            if not project_id or project_role not in PROJECT_ROLES:
                raise AccessError(400, "A member needs a project and a project role.")
            project = session.get(Project, project_id)
            if project is None or project.org_id != org_id:
                raise AccessError(404, "Project not found.")
        user = session.scalar(select(User).where(func.lower(User.email) == clean_email))
        if user is None:
            clean_name = " ".join((name or "").split())
            if len(clean_name) < 2:
                raise AccessError(400, "Enter the member's name.")
            if len(password or "") < 8:
                raise AccessError(400, "Set a password of at least 8 characters for a new member.")
            user = User(
                id=uuid.uuid4().hex,
                username=_username_for(session, clean_email),
                email=clean_email,
                display_name=clean_name[:120],
                password_hash=auth.hash_password(password),
                role="viewer",
                is_active=True,
            )
            session.add(user)
            session.flush()
        existing = session.scalar(
            select(OrgMembership).where(
                OrgMembership.org_id == org_id,
                OrgMembership.user_id == user.id,
            )
        )
        if existing is not None:
            raise AccessError(409, "That person is already in this organization.")
        session.add(
            OrgMembership(
                id=str(uuid.uuid4()),
                org_id=org_id,
                user_id=user.id,
                org_role=clean_role,
            )
        )
        if clean_role == "member":
            session.add(
                ProjectMembership(
                    id=str(uuid.uuid4()),
                    project_id=project_id,
                    user_id=user.id,
                    project_role=project_role,
                )
            )
        session.commit()
        user_id = user.id
    audit(
        org_id=org_id,
        user_id=str(actor["user"]["id"]),
        action="member.add",
        detail=clean_email,
    )
    return {"ok": True, "user_id": user_id, "org_role": clean_role}
