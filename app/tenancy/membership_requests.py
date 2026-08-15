"""DevOps Lead project-member change requests requiring Org Admin approval."""
from __future__ import annotations

import hashlib
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from sqlalchemy import select

from app.core import mailer
from app.tenancy import memberships
from app.core.db import MembershipRequest, Project, SessionLocal, User
from app.core.rbac import normalize_role

REQUEST_TTL_DAYS = 7


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _now() -> datetime:
    return datetime.now(timezone.utc)


def create_request(
    *,
    project_id: str,
    requested_by: dict[str, Any],
    action: str,
    target_email: str = "",
    target_user_id: str = "",
    project_role: str = "developer",
    reason: str = "",
) -> dict[str, Any]:
    action = (action or "add").strip().lower()
    if action not in {"add", "remove", "update_role"}:
        raise ValueError("action must be add, remove, or update_role")
    if not memberships.can_manage_project_members_propose(requested_by, project_id):
        raise PermissionError("DevOps Lead or above required to propose member changes")

    org_id = memberships.project_org_id(project_id)
    if not org_id:
        raise LookupError("Project has no organization")

    # Org Admin / Super Admin can apply immediately without a request.
    if memberships.is_org_admin(requested_by, org_id):
        return _apply_direct(
            project_id=project_id,
            action=action,
            target_email=target_email,
            target_user_id=target_user_id,
            project_role=project_role,
            decided_by=str(requested_by.get("id") or ""),
        )

    email = (target_email or "").strip().lower()
    uid = (target_user_id or "").strip()
    if action == "add" and not email and not uid:
        raise ValueError("target_email or target_user_id required")
    if action in {"remove", "update_role"} and not uid and not email:
        raise ValueError("target_user_id or target_email required")

    raw_token = secrets.token_urlsafe(32)
    with SessionLocal() as session:
        from app.core.db import OrgMembership

        project = session.get(Project, project_id)
        if project is None:
            raise LookupError("Project not found")
        project_name = project.name
        req = MembershipRequest(
            id=str(uuid.uuid4()),
            org_id=org_id,
            project_id=project_id,
            action=action,
            target_email=email,
            target_user_id=uid,
            project_role=normalize_role(project_role),
            status="pending",
            reason=(reason or "").strip()[:2000],
            requested_by=str(requested_by.get("id") or ""),
            approve_token_hash=_hash_token(raw_token),
            expires_at=_now() + timedelta(days=REQUEST_TTL_DAYS),
        )
        session.add(req)
        session.commit()
        request_id = req.id

        admin_users = []
        for m in session.scalars(
            select(OrgMembership).where(
                OrgMembership.org_id == org_id,
                OrgMembership.org_role == "org_admin",
            )
        ).all():
            u = session.get(User, m.user_id)
            if u and (u.email or "").strip():
                admin_users.append(u)

    requester_name = requested_by.get("name") or requested_by.get("username") or "Lead"
    target_label = email or uid
    for admin in admin_users:
        mailer.send_membership_request_email(
            to=admin.email,
            project_name=project_name,
            requester_name=str(requester_name),
            action=action,
            target=target_label,
            approve_token=raw_token,
            request_id=request_id,
        )

    return {
        "id": request_id,
        "status": "pending",
        "action": action,
        "project_id": project_id,
        "org_id": org_id,
        "requires_approval": True,
        "approve_token": raw_token,  # for local/dev when email fails
    }


def _apply_direct(
    *,
    project_id: str,
    action: str,
    target_email: str,
    target_user_id: str,
    project_role: str,
    decided_by: str,
) -> dict[str, Any]:
    user_id = _resolve_user_id(target_user_id, target_email)
    if action == "add":
        if not user_id:
            raise ValueError("User must already exist for direct add; use invite for new emails")
        memberships.ensure_project_membership(
            project_id=project_id, user_id=user_id, project_role=project_role
        )
    elif action == "update_role":
        if not user_id:
            raise LookupError("Target user not found")
        memberships.ensure_project_membership(
            project_id=project_id, user_id=user_id, project_role=project_role
        )
    elif action == "remove":
        if not user_id:
            raise LookupError("Target user not found")
        memberships.remove_project_membership(project_id=project_id, user_id=user_id)
    return {
        "status": "applied",
        "action": action,
        "project_id": project_id,
        "requires_approval": False,
        "decided_by": decided_by,
        "user_id": user_id,
    }


def _resolve_user_id(user_id: str, email: str) -> Optional[str]:
    with SessionLocal() as session:
        if user_id:
            user = session.get(User, user_id)
            return user.id if user else None
        if email:
            user = session.scalar(select(User).where(User.email == email.strip().lower()))
            return user.id if user else None
    return None


def list_requests(*, org_id: str, status: str = "pending") -> list[dict[str, Any]]:
    with SessionLocal() as session:
        q = select(MembershipRequest).where(MembershipRequest.org_id == org_id)
        if status:
            q = q.where(MembershipRequest.status == status)
        rows = session.scalars(q.order_by(MembershipRequest.created_at.desc())).all()
        out = []
        for r in rows:
            project = session.get(Project, r.project_id)
            requester = session.get(User, r.requested_by) if r.requested_by else None
            out.append(
                {
                    "id": r.id,
                    "org_id": r.org_id,
                    "project_id": r.project_id,
                    "project_name": project.name if project else "",
                    "action": r.action,
                    "target_email": r.target_email,
                    "target_user_id": r.target_user_id,
                    "project_role": r.project_role,
                    "status": r.status,
                    "reason": r.reason,
                    "requested_by": r.requested_by,
                    "requester_name": requester.display_name if requester else "",
                    "created_at": r.created_at.isoformat() if r.created_at else None,
                }
            )
        return out


def decide_request(
    *,
    request_id: str,
    decision: str,
    decided_by: dict[str, Any],
    token: Optional[str] = None,
) -> dict[str, Any]:
    decision = (decision or "").strip().lower()
    if decision not in {"approved", "rejected"}:
        raise ValueError("decision must be approved or rejected")

    with SessionLocal() as session:
        req = session.get(MembershipRequest, request_id)
        if req is None:
            raise LookupError("Request not found")
        if req.status != "pending":
            raise ValueError(f"Request is {req.status}")

        # Auth: org admin OR valid email token
        allowed = memberships.is_org_admin(decided_by, req.org_id) if decided_by.get("id") else False
        if token:
            if _hash_token(token) == (req.approve_token_hash or ""):
                allowed = True
        if not allowed:
            raise PermissionError("Org Admin approval required")

        if decision == "rejected":
            req.status = "rejected"
            req.decided_by = str(decided_by.get("id") or "email")
            req.decided_at = _now()
            session.commit()
            return {"id": request_id, "status": "rejected"}

        action = req.action
        project_id = req.project_id
        target_email = req.target_email
        target_user_id = req.target_user_id
        project_role = req.project_role
        req.status = "approved"
        req.decided_by = str(decided_by.get("id") or "email")
        req.decided_at = _now()
        session.commit()

    applied = _apply_direct(
        project_id=project_id,
        action=action,
        target_email=target_email,
        target_user_id=target_user_id,
        project_role=project_role,
        decided_by=str(decided_by.get("id") or "email"),
    )
    applied["id"] = request_id
    applied["status"] = "approved"
    return applied
