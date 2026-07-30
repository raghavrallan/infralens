"""Org Admin+ user and role management (org-scoped)."""
from __future__ import annotations

import uuid
from typing import Any, Optional

from sqlalchemy import select

from app import auth, memberships
from app.db import OrgMembership, SessionLocal, User
from app.rbac import ROLE_LABELS, normalize_role


def list_users(*, org_id: Optional[str] = None, actor: Optional[dict[str, Any]] = None) -> list[dict[str, Any]]:
    with SessionLocal() as session:
        if org_id:
            if actor:
                memberships.assert_org_access(actor, org_id)
            user_ids = [
                m.user_id
                for m in session.scalars(
                    select(OrgMembership).where(OrgMembership.org_id == org_id)
                ).all()
            ]
            if not user_ids:
                return []
            rows = session.scalars(
                select(User).where(User.id.in_(user_ids)).order_by(User.username.asc())
            ).all()
        elif actor and not memberships.is_super_admin(actor):
            # Non-super: union of users across actor's orgs
            org_ids = memberships.user_org_ids(str(actor.get("id") or ""))
            user_ids = set()
            for oid in org_ids:
                for m in session.scalars(
                    select(OrgMembership).where(OrgMembership.org_id == oid)
                ).all():
                    user_ids.add(m.user_id)
            rows = session.scalars(
                select(User).where(User.id.in_(list(user_ids))).order_by(User.username.asc())
            ).all() if user_ids else []
        else:
            rows = session.scalars(select(User).order_by(User.username.asc())).all()
        return [auth._public_user(row) for row in rows]


def create_user(
    *,
    username: str,
    password: str,
    display_name: str = "",
    role: str = "developer",
    email: str = "",
    org_id: Optional[str] = None,
) -> dict[str, Any]:
    clean = (username or "").strip()
    if not clean or len(clean) < 2:
        raise ValueError("Username must be at least 2 characters")
    if not password or len(password) < 6:
        raise ValueError("Password must be at least 6 characters")
    role = normalize_role(role)
    if role not in ROLE_LABELS:
        raise ValueError("Unknown role")
    if role == "super_admin":
        raise ValueError("Cannot create Super Admin via this API")
    with SessionLocal() as session:
        if session.scalar(select(User.id).where(User.username == clean)) is not None:
            raise ValueError("Username already exists")
        row = User(
            id=str(uuid.uuid4()),
            username=clean,
            email=(email or "").strip().lower(),
            display_name=(display_name or clean).strip()[:120],
            password_hash=auth.hash_password(password),
            role=role,
            is_active=True,
        )
        session.add(row)
        session.commit()
        session.refresh(row)
        public = auth._public_user(row)
    if org_id:
        org_role = "org_admin" if role == "org_admin" else "member"
        memberships.ensure_org_membership(
            org_id=org_id, user_id=public["id"], org_role=org_role
        )
    return public


def update_user(
    user_id: str,
    *,
    role: Optional[str] = None,
    is_active: Optional[bool] = None,
    display_name: Optional[str] = None,
    password: Optional[str] = None,
    email: Optional[str] = None,
) -> dict[str, Any]:
    with SessionLocal() as session:
        row = session.get(User, user_id)
        if row is None:
            raise LookupError("User not found")
        if role is not None:
            role_n = normalize_role(role)
            if role_n not in ROLE_LABELS:
                raise ValueError("Unknown role")
            if role_n == "super_admin" and normalize_role(row.role) != "super_admin":
                raise ValueError("Cannot promote to Super Admin here")
            row.role = role_n
        if is_active is not None:
            row.is_active = bool(is_active)
        if display_name is not None and display_name.strip():
            row.display_name = display_name.strip()[:120]
        if email is not None:
            row.email = email.strip().lower()
        if password is not None:
            if len(password) < 6:
                raise ValueError("Password must be at least 6 characters")
            row.password_hash = auth.hash_password(password)
        session.commit()
        session.refresh(row)
        public = auth._public_user(row)
    auth.invalidate_user_cache(user_id)
    return public
