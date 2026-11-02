"""Unified delivery + engineering projection for health, blockers, and UI sync."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import select

from app.core.db import DeliveryRun, SessionLocal
from app.platform.engineering import artifacts as artifact_store
from app.platform.engineering import knowledge, tasks as task_store

STAGE_LABELS = {
    "ingest": "Ingest",
    "architecture": "Architecture",
    "terraform": "Terraform",
    "plan": "Plan",
    "apply": "Apply",
    "code": "Code",
    "done": "Done",
}


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def dashboard_href(*, task_id: str = "", run_id: str = "") -> str:
    """Deep-link to Overview delivery checklist (works from Engineering page)."""
    params: list[str] = ["focus=delivery"]
    if task_id:
        params.append(f"task_id={task_id}")
    if run_id:
        params.append(f"run_id={run_id}")
    return "/dashboard?" + "&".join(params)


def active_delivery_run(project_id: str) -> Optional[dict[str, Any]]:
    with SessionLocal() as session:
        row = session.scalar(
            select(DeliveryRun)
            .where(DeliveryRun.project_id == project_id)
            .order_by(DeliveryRun.updated_at.desc())
        )
        if row is None:
            return None
        artifacts = dict(row.artifacts or {})
        repair = dict(artifacts.get("terraform_repair") or {})
        return {
            "id": row.id,
            "stage": row.stage,
            "stage_label": STAGE_LABELS.get(row.stage, str(row.stage).title()),
            "status": row.status,
            "architecture_status": str(artifacts.get("architecture_status") or ""),
            "terraform_repair": {
                "status": str(repair.get("status") or ""),
                "attempt": int(repair.get("attempt") or repair.get("attempts") or 0),
                "max_attempts": int(repair.get("max_attempts") or 4),
                "progress": str(repair.get("progress") or ""),
                "last_error": str(repair.get("last_error") or repair.get("error") or "")[:800],
            },
            "externally_applied": bool(artifacts.get("externally_applied")),
            "updated_at": row.updated_at.isoformat() if row.updated_at else None,
        }


def stamp_delivery_sync(run_id: str, *, note: str = "") -> None:
    """Mark delivery artifacts so Engineering health can detect freshness."""
    with SessionLocal() as session:
        row = session.get(DeliveryRun, run_id)
        if row is None:
            return
        artifacts = dict(row.artifacts or {})
        artifacts["health_sync_at"] = _iso_now()
        if note:
            artifacts["health_sync_note"] = note[:240]
        row.artifacts = artifacts
        row.updated_at = datetime.now(timezone.utc)
        session.commit()


def project_projection(project_id: str) -> dict[str, Any]:
    """Single source of truth used by health + recommendations."""
    items = task_store.list_tasks(project_id)
    memory_rows = knowledge.list_knowledge(project_id, limit=80)
    artifact_rows = artifact_store.list_artifacts(project_id)
    delivery = active_delivery_run(project_id)
    run_id = str((delivery or {}).get("id") or "")
    return {
        "project_id": project_id,
        "tasks": items,
        "memory": memory_rows,
        "artifacts": artifact_rows,
        "delivery": delivery,
        "delivery_run_id": run_id,
        "task_counts": {
            "total": len(items),
            "completed": sum(1 for item in items if item["status"] == "completed"),
            "blocked": sum(1 for item in items if item["status"] == "blocked"),
            "in_progress": sum(1 for item in items if item["status"] == "in_progress"),
        },
        "synced_at": _iso_now(),
    }
