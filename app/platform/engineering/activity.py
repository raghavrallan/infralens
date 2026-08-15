"""Audit trail helpers."""
from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select

from app.core.db import ProjectActivity, SessionLocal


def record(
    project_id: str,
    action: str,
    *,
    actor: str = "system",
    detail: str = "",
    ref_type: str = "",
    ref_id: str = "",
) -> dict[str, Any]:
    with SessionLocal() as session:
        row = ProjectActivity(
            id=str(uuid.uuid4()),
            project_id=project_id,
            actor=(actor or "system")[:120],
            action=(action or "")[:64],
            detail=(detail or "")[:4000],
            ref_type=(ref_type or "")[:32],
            ref_id=(ref_id or "")[:36],
        )
        session.add(row)
        session.commit()
        return {
            "id": row.id,
            "action": row.action,
            "detail": row.detail,
            "actor": row.actor,
            "created_at": row.created_at.isoformat() if row.created_at else None,
            "ref_type": row.ref_type,
            "ref_id": row.ref_id,
        }


def list_activity(project_id: str, limit: int = 40) -> list[dict[str, Any]]:
    with SessionLocal() as session:
        rows = session.scalars(
            select(ProjectActivity)
            .where(ProjectActivity.project_id == project_id)
            .order_by(ProjectActivity.created_at.desc())
            .limit(max(1, min(limit, 100)))
        ).all()
        return [
            {
                "id": row.id,
                "action": row.action,
                "detail": row.detail,
                "actor": row.actor,
                "created_at": row.created_at.isoformat() if row.created_at else None,
                "ref_type": row.ref_type,
                "ref_id": row.ref_id,
            }
            for row in rows
        ]
