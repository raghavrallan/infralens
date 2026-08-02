"""CRUD and public views for org CLI executor capacity settings."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from sqlalchemy import select

from app.db import Organization, OrgExecutorSettings, Project, SessionLocal
from app.org_executors.schedule import in_warm_window

VALID_MODES = {"on_demand", "window", "schedule"}
VALID_WINDOW_HOURS = {6, 12, 24}
VALID_STATES = {"scaled_to_zero", "warming", "active", "error"}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _public(row: OrgExecutorSettings) -> dict[str, Any]:
    warm = in_warm_window(
        mode=row.mode,
        window_ends_at=row.window_ends_at,
        schedule=row.schedule if isinstance(row.schedule, dict) else {},
    )
    return {
        "org_id": row.org_id,
        "mode": row.mode,
        "window_hours": row.window_hours,
        "window_ends_at": row.window_ends_at.isoformat() if row.window_ends_at else None,
        "schedule": row.schedule or {},
        "idle_scale_down_minutes": row.idle_scale_down_minutes,
        "max_replicas": row.max_replicas,
        "desired_state": row.desired_state,
        "actual_state": row.actual_state,
        "last_job_at": row.last_job_at.isoformat() if row.last_job_at else None,
        "last_error": row.last_error or "",
        "aca_app_names": row.aca_app_names or {},
        "in_warm_window": warm,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


def ensure_settings(org_id: str) -> dict[str, Any]:
    """Create default on-demand settings for an org if missing."""
    with SessionLocal() as session:
        if session.get(Organization, org_id) is None:
            raise LookupError("Organization not found")
        row = session.get(OrgExecutorSettings, org_id)
        if row is None:
            row = OrgExecutorSettings(
                org_id=org_id,
                mode="on_demand",
                window_hours=12,
                idle_scale_down_minutes=15,
                max_replicas=1,
                desired_state="scaled_to_zero",
                actual_state="scaled_to_zero",
            )
            session.add(row)
            session.commit()
            session.refresh(row)
        return _public(row)


def get_settings(org_id: str) -> Optional[dict[str, Any]]:
    with SessionLocal() as session:
        row = session.get(OrgExecutorSettings, org_id)
        if row is None:
            return None
        return _public(row)


def list_all_settings() -> list[dict[str, Any]]:
    with SessionLocal() as session:
        rows = session.scalars(select(OrgExecutorSettings)).all()
        return [_public(row) for row in rows]


def update_settings(
    org_id: str,
    *,
    mode: Optional[str] = None,
    window_hours: Optional[int] = None,
    schedule: Optional[dict[str, Any]] = None,
    idle_scale_down_minutes: Optional[int] = None,
    max_replicas: Optional[int] = None,
    refresh_window: bool = False,
) -> dict[str, Any]:
    ensure_settings(org_id)
    with SessionLocal() as session:
        row = session.get(OrgExecutorSettings, org_id)
        if row is None:
            raise LookupError("Organization not found")
        if mode is not None:
            clean = str(mode).strip().lower()
            if clean not in VALID_MODES:
                raise ValueError("mode must be on_demand, window, or schedule")
            row.mode = clean
        if window_hours is not None:
            hours = int(window_hours)
            if hours not in VALID_WINDOW_HOURS:
                raise ValueError("window_hours must be 6, 12, or 24")
            row.window_hours = hours
        if schedule is not None:
            if not isinstance(schedule, dict):
                raise ValueError("schedule must be an object")
            row.schedule = schedule
        if idle_scale_down_minutes is not None:
            idle = int(idle_scale_down_minutes)
            if idle < 1 or idle > 24 * 60:
                raise ValueError("idle_scale_down_minutes out of range")
            row.idle_scale_down_minutes = idle
        if max_replicas is not None:
            replicas = int(max_replicas)
            if replicas < 1 or replicas > 10:
                raise ValueError("max_replicas must be between 1 and 10")
            row.max_replicas = replicas

        if row.mode == "window" and (refresh_window or row.window_ends_at is None or mode == "window"):
            row.window_ends_at = _now() + timedelta(hours=int(row.window_hours))
            row.desired_state = "active"
        elif row.mode == "on_demand":
            row.window_ends_at = None
        elif row.mode == "schedule":
            row.window_ends_at = None

        row.updated_at = _now()
        session.commit()
        session.refresh(row)
        return _public(row)


def touch_last_job(org_id: str) -> None:
    with SessionLocal() as session:
        row = session.get(OrgExecutorSettings, org_id)
        if row is None:
            return
        row.last_job_at = _now()
        session.commit()


def set_states(
    org_id: str,
    *,
    desired_state: Optional[str] = None,
    actual_state: Optional[str] = None,
    last_error: Optional[str] = None,
    aca_app_names: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    with SessionLocal() as session:
        row = session.get(OrgExecutorSettings, org_id)
        if row is None:
            raise LookupError("Organization executor settings not found")
        if desired_state is not None:
            if desired_state not in VALID_STATES:
                raise ValueError("invalid desired_state")
            row.desired_state = desired_state
        if actual_state is not None:
            if actual_state not in VALID_STATES:
                raise ValueError("invalid actual_state")
            row.actual_state = actual_state
        if last_error is not None:
            row.last_error = last_error[:2000]
        if aca_app_names is not None:
            row.aca_app_names = aca_app_names
        row.updated_at = _now()
        session.commit()
        session.refresh(row)
        return _public(row)


def resolve_org_id_for_project(project_id: str) -> str:
    with SessionLocal() as session:
        project = session.get(Project, project_id)
        if project is None:
            raise LookupError("Project not found")
        org_id = (project.org_id or "").strip()
        if not org_id:
            raise ValueError("Project is not attached to an organization")
        return org_id


def status_payload(org_id: str) -> dict[str, Any]:
    """Settings plus queue depth for the Organizations UI."""
    from app.execution.queue import queue_depth

    cfg = ensure_settings(org_id)
    depth = 0
    try:
        depth = queue_depth(org_id)
    except Exception:  # noqa: BLE001
        depth = 0
    return {
        **cfg,
        "queue_depth": depth,
        "message": _status_message(cfg, depth),
    }


def _status_message(cfg: dict[str, Any], depth: int) -> str:
    state = str(cfg.get("actual_state") or "")
    if state == "error":
        return cfg.get("last_error") or "Executor pool reported an error."
    if state == "warming":
        return "Executor pool is warming up; CLI actions will start shortly."
    if state == "active":
        if depth:
            return f"Executor pool is active with {depth} queued action(s)."
        return "Executor pool is active."
    if cfg.get("in_warm_window"):
        return "Warm window is open but the pool is still scaled to zero."
    if depth:
        return "Actions are queued; wake the executor pool to process them."
    return "Executor pool is scaled to zero (on demand / outside schedule)."
