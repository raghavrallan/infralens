"""Email invites into an organization."""
from __future__ import annotations

import hashlib
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from sqlalchemy import select

from app.core import mailer
from app.tenancy import memberships
from app.core.auth import hash_password
from app.core.db import Invite, Organization, SessionLocal, User
from app.core.rbac import normalize_role

INVITE_TTL_DAYS = 7


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _now() -> datetime:
    return datetime.now(timezone.utc)


def create_invite(
    *,
    org_id: str,
    email: str,
    invited_by: str,
    invited_role: str = "developer",
    org_role: str = "member",
    project_id: Optional[str] = None,
    project_role: str = "developer",
    inviter_name: str = "",
) -> dict[str, Any]:
    clean_email = (email or "").strip().lower()
    if not clean_email or "@" not in clean_email:
        raise ValueError("Valid email is required")
    role = normalize_role(invited_role)
    if role in {"super_admin"}:
        raise ValueError("Cannot invite Super Admin via email")
    org_r = "org_admin" if org_role == "org_admin" else "member"
    if org_r == "org_admin":
        role = "org_admin"

    with SessionLocal() as session:
        org = session.get(Organization, org_id)
        if org is None:
            raise LookupError("Organization not found")
        org_name = org.name

        # Revoke prior pending invites for same email+org.
        for prior in session.scalars(
            select(Invite).where(
                Invite.org_id == org_id,
                Invite.email == clean_email,
                Invite.status == "pending",
            )
        ).all():
            prior.status = "revoked"

        raw_token = secrets.token_urlsafe(32)
        invite = Invite(
            id=str(uuid.uuid4()),
            org_id=org_id,
            email=clean_email,
            token_hash=_hash_token(raw_token),
            invited_role=role,
            org_role=org_r,
            project_id=project_id,
            project_role=normalize_role(project_role),
            status="pending",
            invited_by=invited_by,
            expires_at=_now() + timedelta(days=INVITE_TTL_DAYS),
        )
        session.add(invite)
        session.commit()
        invite_id = invite.id
        expires_at = invite.expires_at

    sent = mailer.send_invite_email(
        to=clean_email,
        org_name=org_name,
        inviter_name=inviter_name or "InfraLens Admin",
        token=raw_token,
    )
    accept_url = f"{mailer.public_app_url()}/accept-invite?token={raw_token}"
    return {
        "id": invite_id,
        "org_id": org_id,
        "email": clean_email,
        "invited_role": role,
        "org_role": org_r,
        "project_id": project_id,
        "status": "pending",
        "email_sent": sent,
        "expires_at": expires_at.isoformat() if expires_at else None,
        # Always return link when SMTP fails so admin can share manually.
        "accept_token": None if sent else raw_token,
        "accept_url": None if sent else accept_url,
        "smtp_error": None if sent else "SMTP unreachable — share accept_url with the invitee",
    }


def list_invites(org_id: str) -> list[dict[str, Any]]:
    with SessionLocal() as session:
        rows = session.scalars(
            select(Invite)
            .where(Invite.org_id == org_id)
            .order_by(Invite.created_at.desc())
        ).all()
        return [
            {
                "id": r.id,
                "org_id": r.org_id,
                "email": r.email,
                "invited_role": r.invited_role,
                "org_role": r.org_role,
                "project_id": r.project_id,
                "status": r.status,
                "invited_by": r.invited_by,
                "expires_at": r.expires_at.isoformat() if r.expires_at else None,
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in rows
        ]


def peek_invite(token: str) -> dict[str, Any]:
    invite = _load_valid_invite(token)
    with SessionLocal() as session:
        org = session.get(Organization, invite.org_id)
        return {
            "email": invite.email,
            "org_id": invite.org_id,
            "org_name": org.name if org else "",
            "invited_role": invite.invited_role,
            "org_role": invite.org_role,
            "project_id": invite.project_id,
            "expires_at": invite.expires_at.isoformat() if invite.expires_at else None,
        }


def _load_valid_invite(token: str) -> Invite:
    token_hash = _hash_token((token or "").strip())
    with SessionLocal() as session:
        invite = session.scalar(select(Invite).where(Invite.token_hash == token_hash))
        if invite is None:
            raise LookupError("Invite not found")
        if invite.status != "pending":
            raise ValueError(f"Invite is {invite.status}")
        expires = invite.expires_at
        if expires is not None and expires.tzinfo is None:
            expires = expires.replace(tzinfo=timezone.utc)
        if expires and expires < _now():
            invite.status = "expired"
            session.commit()
            raise ValueError("Invite expired")
        session.expunge(invite)
        return invite


def accept_invite(
    *,
    token: str,
    password: str,
    display_name: str = "",
    username: Optional[str] = None,
) -> dict[str, Any]:
    if not password or len(password) < 6:
        raise ValueError("Password must be at least 6 characters")
    invite = _load_valid_invite(token)
    email = invite.email
    suggested = (username or email.split("@")[0]).strip().lower()
    suggested = "".join(c for c in suggested if c.isalnum() or c in "._-")[:64] or "user"
    created_new = False

    with SessionLocal() as session:
        invite_row = session.get(Invite, invite.id)
        if invite_row is None or invite_row.status != "pending":
            raise ValueError("Invite no longer valid")

        existing = session.scalar(select(User).where(User.email == email))
        if existing is None:
            existing = session.scalar(select(User).where(User.username == suggested))
        if existing is not None:
            user = existing
            if not user.is_active:
                raise ValueError("User account is disabled")
            user.password_hash = hash_password(password)
            if display_name.strip():
                user.display_name = display_name.strip()[:120]
            if not (user.email or "").strip():
                user.email = email
            if normalize_role(user.role) not in {"super_admin", "org_admin"}:
                user.role = invite_row.invited_role
            login_username = user.username
        else:
            created_new = True
            base = suggested
            candidate = base
            n = 1
            while session.scalar(select(User.id).where(User.username == candidate)):
                n += 1
                candidate = f"{base}{n}"
            user = User(
                id=str(uuid.uuid4()),
                username=candidate,
                email=email,
                display_name=(display_name or candidate).strip()[:120],
                password_hash=hash_password(password),
                role=invite_row.invited_role,
                is_active=True,
            )
            session.add(user)
            session.flush()
            login_username = candidate

        invite_row.status = "accepted"
        invite_row.accepted_at = _now()
        user_id = user.id
        org_id = invite_row.org_id
        org_role = invite_row.org_role
        project_id = invite_row.project_id
        project_role = invite_row.project_role
        session.commit()

    memberships.ensure_org_membership(
        org_id=org_id, user_id=user_id, org_role=org_role
    )
    if project_id:
        memberships.ensure_project_membership(
            project_id=project_id, user_id=user_id, project_role=project_role
        )

    return {
        "ok": True,
        "user_id": user_id,
        "username": login_username,
        "org_id": org_id,
        "project_id": project_id,
        "needs_onboarding": project_id is None,
        "created_new": created_new,
    }
