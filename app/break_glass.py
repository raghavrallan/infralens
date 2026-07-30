"""Break-glass sessions: Lead+ can open a time-boxed one-step gate downgrade."""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from sqlalchemy import select

from app.db import BreakGlassSession, SessionLocal
from app.intelligence.risk_engine import GATE_LABELS, GATE_ORDER


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: Optional[datetime]) -> Optional[str]:
    return value.isoformat() if value else None


def _row_dict(row: BreakGlassSession) -> dict[str, Any]:
    now = _now()
    expired = bool(row.expires_at and row.expires_at <= now)
    active = bool(row.active) and not expired and row.closed_at is None
    return {
        "id": row.id,
        "project_id": row.project_id,
        "opened_by": row.opened_by,
        "reason": row.reason,
        "active": active,
        "postmortem_required": bool(row.postmortem_required),
        "expires_at": _iso(row.expires_at),
        "closed_at": _iso(row.closed_at),
        "created_at": _iso(row.created_at),
        "downgrade_rule": "one_step",
        "audit": {
            "event": "break_glass",
            "postmortem_required": True,
        },
    }


def open_session(
    project_id: str,
    *,
    opened_by: str,
    reason: str,
    ttl_minutes: int = 60,
) -> dict[str, Any]:
    reason_clean = (reason or "").strip()
    if len(reason_clean) < 8:
        raise ValueError("Break-glass requires a reason (min 8 characters)")
    ttl = max(5, min(int(ttl_minutes or 60), 240))
    # Expire any prior active sessions for this project.
    with SessionLocal() as session:
        for prior in session.scalars(
            select(BreakGlassSession).where(
                BreakGlassSession.project_id == project_id,
                BreakGlassSession.active.is_(True),
                BreakGlassSession.closed_at.is_(None),
            )
        ):
            prior.active = False
            prior.closed_at = _now()
        row = BreakGlassSession(
            id=str(uuid.uuid4()),
            project_id=project_id,
            opened_by=(opened_by or "operator")[:120],
            reason=reason_clean[:2000],
            active=True,
            postmortem_required=True,
            expires_at=_now() + timedelta(minutes=ttl),
        )
        session.add(row)
        session.commit()
        session.refresh(row)
        return _row_dict(row)


def status(project_id: str) -> dict[str, Any]:
    with SessionLocal() as session:
        rows = list(
            session.scalars(
                select(BreakGlassSession)
                .where(BreakGlassSession.project_id == project_id)
                .order_by(BreakGlassSession.created_at.desc())
                .limit(20)
            )
        )
        # Auto-expire.
        now = _now()
        changed = False
        for row in rows:
            if row.active and row.closed_at is None and row.expires_at and row.expires_at <= now:
                row.active = False
                row.closed_at = now
                changed = True
        if changed:
            session.commit()
        active = next((r for r in rows if _row_dict(r)["active"]), None)
        return {
            "active": _row_dict(active) if active else None,
            "history": [_row_dict(r) for r in rows],
        }


def expire(project_id: str, session_id: Optional[str] = None) -> dict[str, Any]:
    with SessionLocal() as session:
        query = select(BreakGlassSession).where(
            BreakGlassSession.project_id == project_id,
            BreakGlassSession.active.is_(True),
        )
        if session_id:
            query = query.where(BreakGlassSession.id == session_id)
        rows = list(session.scalars(query))
        now = _now()
        for row in rows:
            row.active = False
            row.closed_at = now
        session.commit()
        return status(project_id)


def is_active(project_id: str) -> bool:
    """True when an unexpired break-glass window is open (single indexed lookup)."""
    now = _now()
    with SessionLocal() as session:
        row = session.scalar(
            select(BreakGlassSession.id)
            .where(
                BreakGlassSession.project_id == project_id,
                BreakGlassSession.active.is_(True),
                BreakGlassSession.closed_at.is_(None),
                BreakGlassSession.expires_at > now,
            )
            .limit(1)
        )
        return row is not None


def downgrade_gate(gate: str, project_id: str, *, active: Optional[bool] = None) -> str:
    """If break-glass is active, soften the gate by exactly one step."""
    if active is None:
        active = is_active(project_id)
    if not active:
        return gate
    if gate not in GATE_ORDER:
        return gate
    idx = GATE_ORDER.index(gate)  # type: ignore[arg-type]
    if idx <= 0:
        return gate
    return GATE_ORDER[idx - 1]


def gate_with_break_glass(
    gate: str, project_id: str, *, active: Optional[bool] = None
) -> dict[str, Any]:
    effective = downgrade_gate(gate, project_id, active=active)
    return {
        "gate": effective,
        "gate_label": GATE_LABELS.get(effective, effective),  # type: ignore[arg-type]
        "original_gate": gate,
        "break_glass_applied": effective != gate,
    }
