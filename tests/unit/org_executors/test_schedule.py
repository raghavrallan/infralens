"""Org executor schedule windows, overnight ranges, and warm modes."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.org_executors.schedule import in_schedule_window, in_warm_window


@pytest.mark.unit
def test_empty_schedule_is_off():
    now = datetime(2026, 8, 3, 10, 0, tzinfo=timezone.utc)
    assert in_schedule_window(None, now=now) is False
    assert in_schedule_window({}, now=now) is False


@pytest.mark.unit
def test_absolute_window():
    now = datetime(2026, 8, 2, 12, 0, tzinfo=timezone.utc)
    schedule = {
        "absolute": [
            {"start": "2026-08-02T09:00:00Z", "end": "2026-08-02T18:00:00Z"},
            {"start": "bad", "end": "also-bad"},
            "ignore-me",
        ]
    }
    assert in_schedule_window(schedule, now=now) is True
    assert in_schedule_window(
        schedule, now=datetime(2026, 8, 2, 20, 0, tzinfo=timezone.utc)
    ) is False


@pytest.mark.unit
def test_weekly_overnight_and_invalid_timezone():
    now = datetime(2026, 8, 3, 23, 30, tzinfo=timezone.utc)  # Monday
    schedule = {
        "timezone": "Not/AZone",
        "weekly": [{"days": [0], "start": "22:00", "end": "06:00"}],
    }
    assert in_schedule_window(schedule, now=now) is True
    morning = datetime(2026, 8, 4, 5, 0, tzinfo=timezone.utc)  # Tuesday 05:00 UTC
    # Overnight Monday 22:00–06:00 does not include Tuesday unless days include Tuesday.
    assert in_schedule_window(schedule, now=morning) is False
    both_days = {
        "timezone": "UTC",
        "weekly": [{"days": [0, 1], "start": "22:00", "end": "06:00"}],
    }
    assert in_schedule_window(both_days, now=morning) is True


@pytest.mark.unit
def test_naive_now_is_treated_as_utc():
    now = datetime(2026, 8, 3, 10, 0)
    schedule = {"weekly": [{"days": [0], "start": "09:00", "end": "18:00"}]}
    assert in_schedule_window(schedule, now=now) is True


@pytest.mark.unit
def test_invalid_weekly_entries_are_skipped():
    now = datetime(2026, 8, 3, 10, 0, tzinfo=timezone.utc)
    schedule = {
        "weekly": [
            "nope",
            {"days": ["x"], "start": "09:00", "end": "18:00"},
            {"days": [0], "start": "bad", "end": "18:00"},
            {"days": [1], "start": "09:00", "end": "18:00"},
        ]
    }
    assert in_schedule_window(schedule, now=now) is False


@pytest.mark.unit
def test_in_warm_window_modes():
    now = datetime(2026, 8, 3, 10, 0, tzinfo=timezone.utc)
    assert in_warm_window(mode="on_demand", window_ends_at=None, schedule={}, now=now) is False
    assert in_warm_window(mode="window", window_ends_at=None, schedule={}, now=now) is False
    ends = now + timedelta(hours=1)
    assert in_warm_window(mode="window", window_ends_at=ends, schedule={}, now=now) is True
    naive_end = datetime(2026, 8, 3, 12, 0)
    assert in_warm_window(mode="window", window_ends_at=naive_end, schedule={}, now=now) is True
    assert in_warm_window(
        mode="schedule",
        window_ends_at=None,
        schedule={"weekly": [{"days": [0], "start": "09:00", "end": "18:00"}]},
        now=now,
    )
