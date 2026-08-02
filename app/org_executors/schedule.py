"""Schedule window evaluation for org executor pools."""
from __future__ import annotations

from datetime import datetime, time, timezone
from typing import Any
from zoneinfo import ZoneInfo


def _parse_hhmm(value: str) -> time | None:
    raw = (value or "").strip()
    if not raw:
        return None
    try:
        hour, minute = raw.split(":", 1)
        return time(hour=int(hour), minute=int(minute))
    except (TypeError, ValueError):
        return None


def in_schedule_window(schedule: dict[str, Any] | None, *, now: datetime | None = None) -> bool:
    """Return True when *now* falls inside a configured custom schedule.

    Schedule JSON shape:
      {
        "timezone": "UTC",
        "weekly": [{"days": [0,1,2,3,4], "start": "09:00", "end": "18:00"}],
        "absolute": [{"start": "2026-08-02T09:00:00Z", "end": "2026-08-02T18:00:00Z"}]
      }
    Days are Monday=0 … Sunday=6.
    Outside any window returns False (hard off).
    """
    payload = schedule or {}
    now_utc = now or datetime.now(timezone.utc)
    if now_utc.tzinfo is None:
        now_utc = now_utc.replace(tzinfo=timezone.utc)

    absolute = payload.get("absolute") if isinstance(payload.get("absolute"), list) else []
    for item in absolute:
        if not isinstance(item, dict):
            continue
        try:
            start = datetime.fromisoformat(str(item.get("start", "")).replace("Z", "+00:00"))
            end = datetime.fromisoformat(str(item.get("end", "")).replace("Z", "+00:00"))
        except ValueError:
            continue
        if start.tzinfo is None:
            start = start.replace(tzinfo=timezone.utc)
        if end.tzinfo is None:
            end = end.replace(tzinfo=timezone.utc)
        if start <= now_utc < end:
            return True

    weekly = payload.get("weekly") if isinstance(payload.get("weekly"), list) else []
    if not weekly and not absolute:
        return False

    tz_name = str(payload.get("timezone") or "UTC")
    try:
        tz = ZoneInfo(tz_name)
    except Exception:  # noqa: BLE001
        tz = ZoneInfo("UTC")
    local = now_utc.astimezone(tz)
    weekday = local.weekday()
    current = local.timetz().replace(tzinfo=None)

    for item in weekly:
        if not isinstance(item, dict):
            continue
        days = item.get("days") if isinstance(item.get("days"), list) else []
        try:
            day_set = {int(d) for d in days}
        except (TypeError, ValueError):
            continue
        if weekday not in day_set:
            continue
        start = _parse_hhmm(str(item.get("start") or ""))
        end = _parse_hhmm(str(item.get("end") or ""))
        if start is None or end is None:
            continue
        if start <= end:
            if start <= current < end:
                return True
        else:
            # Overnight window, e.g. 22:00–06:00
            if current >= start or current < end:
                return True
    return False


def in_warm_window(
    *,
    mode: str,
    window_ends_at: datetime | None,
    schedule: dict[str, Any] | None,
    now: datetime | None = None,
) -> bool:
    """Whether the org pool should stay warm right now."""
    now_utc = now or datetime.now(timezone.utc)
    if now_utc.tzinfo is None:
        now_utc = now_utc.replace(tzinfo=timezone.utc)
    if mode == "window":
        if window_ends_at is None:
            return False
        ends = window_ends_at
        if ends.tzinfo is None:
            ends = ends.replace(tzinfo=timezone.utc)
        return now_utc < ends
    if mode == "schedule":
        return in_schedule_window(schedule, now=now_utc)
    return False
