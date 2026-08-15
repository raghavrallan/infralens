"""Executor control-plane claim/result/cancel after a queued action exists."""
from __future__ import annotations

from unittest.mock import patch

import pytest

from app.execution import service as execution
from app.platform import connections


pytestmark = pytest.mark.integration


def _headers(org_id: str) -> dict[str, str]:
    return {
        "X-Executor-Key": "test-executor-key",
        "X-Executor-Provider": "azure",
        "X-Executor-Org-Id": org_id,
    }


def test_executor_claim_event_result_and_canceled(client, org_with_project):
    project_id = org_with_project["project"]["id"]
    org_id = org_with_project["org"]["id"]
    connections.set_connection(
        project_id,
        "azure",
        "client_secret",
        {
            "tenant_id": "t",
            "client_id": "c",
            "client_secret": "s",
            "subscription_id": "sub",
        },
    )
    with patch("app.execution.service.enqueue_action", return_value={"executor_available": True}):
        with patch("app.execution.service.request_wake"):
            action = execution.create_action(
                project_id=project_id,
                provider="azure",
                executable="az",
                args=["account", "show", "--output", "json"],
                target="identity",
                access_scope="read_only",
                expected_result="ok",
                risk="",
                rollback="n/a",
                preflight=[],
                verify=[],
            )
    headers = _headers(org_id)
    claimed = client.get(
        f"/internal/execution/jobs/{action['id']}/claim",
        params={"provider": "azure"},
        headers=headers,
    )
    assert claimed.status_code == 200
    event = client.post(
        f"/internal/execution/jobs/{action['id']}/events",
        json={"type": "action_output", "payload": {"line": "ok"}},
        headers=headers,
    )
    assert event.status_code == 200
    canceled = client.get(
        f"/internal/execution/jobs/{action['id']}/canceled",
        params={"provider": "azure"},
        headers=headers,
    )
    assert canceled.status_code == 200
    result = client.post(
        f"/internal/execution/jobs/{action['id']}/result",
        json={"status": "succeeded", "result": {"stdout": "{}"}, "error": ""},
        headers=headers,
    )
    assert result.status_code in {200, 409}
    mismatch = client.get(
        f"/internal/execution/jobs/{action['id']}/claim",
        params={"provider": "aws"},
        headers=headers,
    )
    assert mismatch.status_code == 403


def test_execute_plan_missing_chat_and_empty_steps(client, org_with_project):
    headers = {"Authorization": f"Bearer {org_with_project['admin']['token']}"}
    missing = client.post(
        "/api/chat/execute-plan",
        json={
            "chat_id": "missing",
            "project_id": org_with_project["project"]["id"],
            "steps": [{"skill": "report_writer", "objective": "write"}],
        },
        headers=headers,
    )
    assert missing.status_code == 404
    from app.chat import chats

    chat = chats.create_chat("plan", project_id=org_with_project["project"]["id"])
    empty = client.post(
        "/api/chat/execute-plan",
        json={
            "chat_id": chat["id"],
            "project_id": org_with_project["project"]["id"],
            "steps": [{"skill": "not_real", "objective": "x"}],
        },
        headers=headers,
    )
    assert empty.status_code == 400


def test_oauth_start_without_env_returns_error(client, org_with_project):
    headers = {"Authorization": f"Bearer {org_with_project['admin']['token']}"}
    github = client.get(
        f"/api/providers/github/oauth/start?project_id={org_with_project['project']['id']}",
        headers=headers,
    )
    assert github.status_code in {400, 500, 503}
    azure = client.get(
        f"/api/providers/azure/oauth/start?project_id={org_with_project['project']['id']}",
        headers=headers,
    )
    assert azure.status_code in {400, 500, 503}
