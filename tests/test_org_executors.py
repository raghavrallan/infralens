"""Org-scoped executor queues, claim isolation, and capacity settings."""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest

from app import connections, orgs, projects
from app.auth import hash_password
from app.db import ExecutionJob, SessionLocal, User, init_db
from app.execution import queue as exec_queue
from app.execution import service as execution
from app.org_executors import settings as org_settings
from app.org_executors.controller import request_wake, tick_once
from app.org_executors.schedule import in_schedule_window, in_warm_window


def _mk_user(*, username: str, role: str = "developer") -> dict:
    with SessionLocal() as session:
        row = User(
            id=str(uuid.uuid4()),
            username=username,
            email=f"{username}@example.com",
            display_name=username,
            password_hash=hash_password("secret12"),
            role=role,
            is_active=True,
        )
        session.add(row)
        session.commit()
        return {
            "id": row.id,
            "username": row.username,
            "name": row.display_name,
            "role": role,
            "email": row.email,
        }


def _queued_job(*, project_id: str, provider: str = "azure") -> str:
    action_id = str(uuid4())
    with SessionLocal() as session:
        session.add(
            ExecutionJob(
                id=action_id,
                project_id=project_id,
                provider=provider,
                operation={
                    "provider": provider,
                    "executable": "az",
                    "args": ["account", "show"],
                    "target": "identity",
                },
                target="identity",
                access_scope="read_only",
                status="queued",
                requested_by="tester",
                command_preview="az account show",
                operation_hash="hash",
            )
        )
        session.commit()
    return action_id


def test_queue_names_are_org_scoped():
    org_a = "org-aaa"
    org_b = "org-bbb"
    assert exec_queue.queue_name(org_a, "azure", "read_only") == (
        "org.org-aaa.provider.azure.read"
    )
    assert exec_queue.queue_name(org_a, "azure", "write") == (
        "org.org-aaa.provider.azure.write"
    )
    assert exec_queue.queue_name(org_a, "azure", "read_only") != exec_queue.queue_name(
        org_b, "azure", "read_only"
    )
    with pytest.raises(ValueError):
        exec_queue.queue_name("", "azure", "read_only")


def test_schedule_weekly_and_window_modes():
    now = datetime(2026, 8, 3, 10, 0, tzinfo=timezone.utc)
    assert in_schedule_window(
        {
            "timezone": "UTC",
            "weekly": [{"days": [0], "start": "09:00", "end": "18:00"}],
        },
        now=now,
    )
    assert not in_schedule_window(
        {
            "timezone": "UTC",
            "weekly": [{"days": [0], "start": "09:00", "end": "18:00"}],
        },
        now=datetime(2026, 8, 3, 20, 0, tzinfo=timezone.utc),
    )
    ends = now + timedelta(hours=6)
    assert in_warm_window(mode="window", window_ends_at=ends, schedule={}, now=now)
    assert not in_warm_window(
        mode="window",
        window_ends_at=now - timedelta(minutes=1),
        schedule={},
        now=now,
    )
    assert not in_warm_window(mode="on_demand", window_ends_at=None, schedule={}, now=now)


def test_cross_org_claim_rejection_and_same_org_multi_project():
    init_db()
    admin = _mk_user(username=f"sa_{uuid.uuid4().hex[:8]}", role="super_admin")
    org_a = orgs.create_org(name=f"ExecA-{uuid.uuid4().hex[:6]}", created_by=admin["id"])
    org_b = orgs.create_org(name=f"ExecB-{uuid.uuid4().hex[:6]}", created_by=admin["id"])
    pa1 = projects.create_project(
        "A1", org_id=org_a["id"], owner_user_id=admin["id"], owner_project_role="devops_lead"
    )
    pa2 = projects.create_project(
        "A2", org_id=org_a["id"], owner_user_id=admin["id"], owner_project_role="devops_lead"
    )
    pb = projects.create_project(
        "B1", org_id=org_b["id"], owner_user_id=admin["id"], owner_project_role="devops_lead"
    )

    connections.set_connection(
        pa1["id"],
        "azure",
        "client_secret",
        {
            "tenant_id": "t",
            "client_id": "c",
            "client_secret": "s",
            "subscription_id": "sub",
        },
    )
    connections.set_connection(
        pa2["id"],
        "azure",
        "client_secret",
        {
            "tenant_id": "t2",
            "client_id": "c2",
            "client_secret": "s2",
            "subscription_id": "sub2",
        },
    )
    connections.set_connection(
        pb["id"],
        "azure",
        "client_secret",
        {
            "tenant_id": "tb",
            "client_id": "cb",
            "client_secret": "sb",
            "subscription_id": "subb",
        },
    )

    assert org_settings.resolve_org_id_for_project(pa1["id"]) == org_a["id"]
    assert org_settings.resolve_org_id_for_project(pa2["id"]) == org_a["id"]
    q1 = exec_queue.queue_name(org_a["id"], "azure", "read_only")
    q2 = exec_queue.queue_name(
        org_settings.resolve_org_id_for_project(pa2["id"]), "azure", "read_only"
    )
    assert q1 == q2
    assert q1 != exec_queue.queue_name(org_b["id"], "azure", "read_only")

    action_a1 = _queued_job(project_id=pa1["id"])
    action_a2 = _queued_job(project_id=pa2["id"])
    action_b = _queued_job(project_id=pb["id"])

    claimed = execution.claim_for_executor(
        action_a1, "azure", executor_org_id=org_a["id"]
    )
    assert claimed["org_id"] == org_a["id"]
    assert claimed["project_id"] == pa1["id"]
    assert claimed["credentials"]["client_id"] == "c"

    claimed2 = execution.claim_for_executor(
        action_a2, "azure", executor_org_id=org_a["id"]
    )
    assert claimed2["project_id"] == pa2["id"]
    assert claimed2["credentials"]["client_id"] == "c2"

    with pytest.raises(ValueError, match="org"):
        execution.claim_for_executor(action_b, "azure", executor_org_id=org_a["id"])

    with pytest.raises(ValueError, match="org"):
        execution.validate_executor_org(action_b, org_a["id"])

    fresh = _queued_job(project_id=pa1["id"])
    with pytest.raises(ValueError, match="required"):
        execution.claim_for_executor(fresh, "azure", executor_org_id="")


def test_executor_settings_modes_and_wake(monkeypatch):
    init_db()
    admin = _mk_user(username=f"sa_{uuid.uuid4().hex[:8]}", role="super_admin")
    org = orgs.create_org(name=f"Scale-{uuid.uuid4().hex[:6]}", created_by=admin["id"])
    cfg = org_settings.ensure_settings(org["id"])
    assert cfg["mode"] == "on_demand"

    scaled = []

    def fake_scale(org_id, *, min_replicas, max_replicas, app_names=None):
        scaled.append(
            {
                "org_id": org_id,
                "min": min_replicas,
                "max": max_replicas,
                "apps": dict(app_names or {}),
            }
        )
        return {"azure": "app-az", "aws": "app-aws", "github": "app-gh"}

    monkeypatch.setattr("app.org_executors.controller.apply_scale", fake_scale)
    monkeypatch.setattr("app.org_executors.controller.queue_depth", lambda org_id: 0)

    updated = org_settings.update_settings(
        org["id"], mode="window", window_hours=6, refresh_window=True, max_replicas=2
    )
    assert updated["mode"] == "window"
    assert updated["window_hours"] == 6
    assert updated["window_ends_at"]
    assert updated["in_warm_window"] is True

    results = tick_once(org["id"])
    assert results
    assert results[0]["desired"] == "active"
    assert scaled
    assert scaled[-1]["min"] >= 1
    assert scaled[-1]["max"] == 2

    org_settings.update_settings(org["id"], mode="on_demand")
    monkeypatch.setattr("app.org_executors.controller.queue_depth", lambda org_id: 3)
    wake = request_wake(org["id"])
    assert wake["org_id"] == org["id"]
    status = org_settings.status_payload(org["id"])
    assert status["org_id"] == org["id"]
    assert "message" in status
