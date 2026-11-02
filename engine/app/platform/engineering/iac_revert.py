"""Gated revert of an isolated Terraform apply.

Super Admin and Org Admin can destroy the isolated stack. Other project
members raise a request those admins approve or reject.
"""
from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select

from app.core.db import Project, RevertRequest, SessionLocal, User, _now
from app.core.rbac import has_min_role
from app.tenancy import memberships


def can_execute_revert(user: dict[str, Any], project_id: str) -> bool:
    role = memberships.effective_role_for_project(user, project_id)
    return has_min_role(role, "org_admin")


def _user_label(user_id: str) -> str:
    if not user_id:
        return ""
    with SessionLocal() as session:
        row = session.get(User, user_id)
        if row is None:
            return user_id
        return (row.display_name or row.username or user_id).strip()


def _serialize(row: RevertRequest) -> dict[str, Any]:
    return {
        "id": row.id,
        "org_id": row.org_id,
        "project_id": row.project_id,
        "delivery_run_id": row.delivery_run_id,
        "status": row.status,
        "reason": row.reason,
        "requested_by": row.requested_by,
        "requested_by_name": _user_label(row.requested_by),
        "decided_by": row.decided_by,
        "decided_by_name": _user_label(row.decided_by),
        "decided_at": row.decided_at.isoformat() if row.decided_at else None,
        "executed_at": row.executed_at.isoformat() if row.executed_at else None,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


def _remember(run_id: str, payload: dict[str, Any]) -> None:
    from app.platform.engineering import iac_delivery

    iac_delivery._patch(run_id, {"revert_request": payload})


def list_requests(run_id: str, *, project_id: str = "") -> list[dict[str, Any]]:
    with SessionLocal() as session:
        stmt = select(RevertRequest).where(RevertRequest.delivery_run_id == run_id)
        if project_id:
            stmt = stmt.where(RevertRequest.project_id == project_id)
        rows = session.scalars(stmt.order_by(RevertRequest.created_at.desc())).all()
        return [_serialize(row) for row in rows]


def create_request(run_id: str, user: dict[str, Any], *, reason: str = "") -> dict[str, Any]:
    from app.platform.engineering import iac_delivery

    row = iac_delivery._run(run_id)
    project_id = row["project_id"]
    apply = dict((row.get("artifacts") or {}).get("apply_result") or {})
    if apply.get("status") not in {"applied", "failed", "reverted", "reverting"}:
        raise ValueError("Nothing to revert. Apply isolated infrastructure first.")
    org_id = memberships.project_org_id(project_id) or ""
    requester = str(user.get("id") or "")
    with SessionLocal() as session:
        existing = session.scalar(
            select(RevertRequest).where(
                RevertRequest.delivery_run_id == run_id,
                RevertRequest.status == "pending",
            )
        )
        if existing is not None:
            payload = _serialize(existing)
            _remember(run_id, payload)
            return payload
        project = session.get(Project, project_id)
        req = RevertRequest(
            id=str(uuid.uuid4()),
            org_id=org_id or str(getattr(project, "org_id", "") or ""),
            project_id=project_id,
            delivery_run_id=run_id,
            status="pending",
            reason=(reason or "").strip()[:2000],
            requested_by=requester,
        )
        session.add(req)
        session.commit()
        payload = _serialize(req)
    _remember(run_id, payload)
    return payload


def decide_request(
    run_id: str,
    request_id: str,
    user: dict[str, Any],
    *,
    approve: bool,
    confirm: bool = False,
) -> dict[str, Any]:
    from app.platform.engineering import iac_delivery

    row = iac_delivery._run(run_id)
    if not can_execute_revert(user, row["project_id"]):
        raise PermissionError("Reverting applied infrastructure requires Org Admin or Super Admin")
    if approve and not confirm:
        raise ValueError("Approve revert with confirm=true to destroy the isolated stack.")
    with SessionLocal() as session:
        req = session.get(RevertRequest, request_id)
        if req is None or req.delivery_run_id != run_id:
            raise LookupError("Revert request not found")
        if req.status != "pending":
            raise ValueError("Revert request is not pending")
        req.decided_by = str(user.get("id") or "")
        req.decided_at = _now()
        req.status = "approved" if approve else "rejected"
        session.commit()
        payload = _serialize(req)
    _remember(run_id, payload)
    if not approve:
        return {"request": payload, "run": iac_delivery._run(run_id)}
    run = iac_delivery.run_destroy(run_id, confirm=True)
    with SessionLocal() as session:
        req = session.get(RevertRequest, request_id)
        if req is not None:
            revert = dict((run.get("artifacts") or {}).get("revert_result") or {})
            req.status = "executed" if revert.get("status") == "reverted" else "failed"
            req.executed_at = _now()
            session.commit()
            payload = _serialize(req)
    _remember(run_id, payload)
    return {"request": payload, "run": run}


def request_or_run(
    run_id: str,
    user: dict[str, Any],
    *,
    confirm: bool = False,
    reason: str = "",
) -> dict[str, Any]:
    from app.platform.engineering import iac_delivery

    row = iac_delivery._run(run_id)
    if can_execute_revert(user, row["project_id"]):
        return {"mode": "executed", "run": iac_delivery.run_destroy(run_id, confirm=confirm)}
    payload = create_request(run_id, user, reason=reason)
    return {"mode": "requested", "request": payload, "run": iac_delivery._run(run_id)}
