"""Engineering Memory retrieval for informed approvals and risk context."""
from __future__ import annotations

from typing import Any, Optional

from sqlalchemy import select

from app.db import EngineeringMemory, SessionLocal


def _row_dict(row: EngineeringMemory) -> dict[str, Any]:
    return {
        "id": row.id,
        "kind": row.kind,
        "ref_id": row.ref_id,
        "summary": row.summary,
        "outcome": row.outcome,
        "payload": dict(row.payload or {}),
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


def list_recent(project_id: str, *, limit: int = 50) -> list[dict[str, Any]]:
    """Load recent memory rows once for batch filtering in list endpoints."""
    with SessionLocal() as session:
        rows = list(
            session.scalars(
                select(EngineeringMemory)
                .where(EngineeringMemory.project_id == project_id)
                .order_by(EngineeringMemory.created_at.desc())
                .limit(max(1, min(limit, 200)))
            )
        )
        return [_row_dict(row) for row in rows]


def filter_precedent(
    rows: list[dict[str, Any]],
    *,
    skill: Optional[str] = None,
    module: Optional[str] = None,
    resource: Optional[str] = None,
    limit: int = 10,
) -> list[dict[str, Any]]:
    """Filter preloaded memory rows without additional DB round-trips."""
    results: list[dict[str, Any]] = []
    for row in rows:
        payload = row.get("payload") or {}
        if skill and payload.get("skill") and payload.get("skill") != skill:
            continue
        if module and payload.get("module") and payload.get("module") != module:
            continue
        if resource and payload.get("resource"):
            if resource.lower() not in str(payload.get("resource")).lower():
                continue
        # List payloads only need summary/outcome for the dashboard strip.
        results.append(
            {
                "id": row.get("id"),
                "kind": row.get("kind"),
                "ref_id": row.get("ref_id"),
                "summary": row.get("summary"),
                "outcome": row.get("outcome"),
                "created_at": row.get("created_at"),
            }
        )
        if len(results) >= max(1, min(limit, 50)):
            break
    return results


def list_precedent(
    project_id: str,
    *,
    skill: Optional[str] = None,
    module: Optional[str] = None,
    resource: Optional[str] = None,
    limit: int = 10,
) -> list[dict[str, Any]]:
    # Over-fetch then filter so skill/module matches are not truncated by LIMIT.
    rows = list_recent(project_id, limit=max(50, limit * 10))
    return filter_precedent(
        rows, skill=skill, module=module, resource=resource, limit=limit
    )


def remember_action(
    *,
    project_id: str,
    action_id: str,
    summary: str,
    outcome: str,
    payload: Optional[dict[str, Any]] = None,
) -> None:
    import uuid

    with SessionLocal() as session:
        session.add(
            EngineeringMemory(
                id=str(uuid.uuid4()),
                project_id=project_id,
                kind="action",
                ref_id=action_id,
                summary=(summary or "")[:2000],
                outcome=(outcome or "")[:32],
                payload=payload or {},
            )
        )
        session.commit()
