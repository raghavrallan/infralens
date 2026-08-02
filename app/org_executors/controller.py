"""Background scale controller for org CLI executor pools."""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from apscheduler.schedulers.background import BackgroundScheduler

from app.execution.queue import queue_depth
from app.org_executors import settings as store
from app.org_executors.schedule import in_warm_window
from app.org_executors.scaler import apply_scale, scaler_kind

logger = logging.getLogger(__name__)

_scheduler: BackgroundScheduler | None = None
_POLL_SECONDS = 30


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _should_be_active(cfg: dict[str, Any], depth: int) -> bool:
    mode = str(cfg.get("mode") or "on_demand")
    if in_warm_window(
        mode=mode,
        window_ends_at=_parse_dt(cfg.get("window_ends_at")),
        schedule=cfg.get("schedule") if isinstance(cfg.get("schedule"), dict) else {},
    ):
        return True
    if mode == "on_demand":
        if depth > 0:
            return True
        last_job = _parse_dt(cfg.get("last_job_at"))
        if last_job is None:
            return False
        idle_minutes = int(cfg.get("idle_scale_down_minutes") or 15)
        age = (_now() - last_job).total_seconds() / 60.0
        return age < idle_minutes
    # schedule mode outside window: hard off
    return False


def _parse_dt(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def tick_once(org_id: str | None = None) -> list[dict[str, Any]]:
    """Evaluate and apply scale for one org or all orgs."""
    results: list[dict[str, Any]] = []
    configs = [store.ensure_settings(org_id)] if org_id else store.list_all_settings()
    for cfg in configs:
        oid = str(cfg["org_id"])
        try:
            depth = queue_depth(oid)
        except Exception:  # noqa: BLE001
            depth = 0
        want_active = _should_be_active(cfg, depth)
        max_replicas = max(1, int(cfg.get("max_replicas") or 1))
        # Bump toward max when queue is busy during an active period.
        min_replicas = 0
        if want_active:
            min_replicas = 1 if depth <= 1 else min(max_replicas, max(1, depth))
        desired = "active" if want_active else "scaled_to_zero"
        if want_active and str(cfg.get("actual_state")) in {"scaled_to_zero", "error", "warming"}:
            desired = "warming" if str(cfg.get("actual_state")) != "active" else "active"
        try:
            store.set_states(oid, desired_state=desired if want_active else "scaled_to_zero")
            if want_active and str(cfg.get("actual_state")) == "scaled_to_zero":
                store.set_states(oid, actual_state="warming", last_error="")
            names = apply_scale(
                oid,
                min_replicas=min_replicas,
                max_replicas=max_replicas,
                app_names=cfg.get("aca_app_names") if isinstance(cfg.get("aca_app_names"), dict) else {},
            )
            actual = "active" if want_active else "scaled_to_zero"
            store.set_states(
                oid,
                desired_state=actual,
                actual_state=actual,
                last_error="",
                aca_app_names=names,
            )
            results.append(
                {
                    "org_id": oid,
                    "desired": actual,
                    "min_replicas": min_replicas,
                    "max_replicas": max_replicas,
                    "queue_depth": depth,
                    "backend": scaler_kind(),
                }
            )
        except Exception as exc:  # noqa: BLE001
            logger.exception("Org executor scale failed for %s", oid)
            try:
                store.set_states(oid, actual_state="error", last_error=str(exc)[:2000])
            except Exception:  # noqa: BLE001
                pass
            results.append({"org_id": oid, "error": str(exc)[:300]})
    return results


def request_wake(org_id: str) -> dict[str, Any]:
    """Mark activity and immediately attempt scale-up for an org pool."""
    store.ensure_settings(org_id)
    store.touch_last_job(org_id)
    store.set_states(org_id, desired_state="warming", last_error="")
    results = tick_once(org_id)
    return results[0] if results else {"org_id": org_id, "desired": "warming"}


def start_controller() -> None:
    global _scheduler
    if _scheduler is not None:
        return
    _scheduler = BackgroundScheduler()
    _scheduler.add_job(
        tick_once,
        "interval",
        seconds=_POLL_SECONDS,
        id="org-executor-scale",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )
    _scheduler.start()
    logger.info("Org executor scale controller started (every %ss)", _POLL_SECONDS)


def stop_controller() -> None:
    global _scheduler
    if _scheduler is None:
        return
    _scheduler.shutdown(wait=False)
    _scheduler = None
