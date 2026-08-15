"""Execution service approve/claim/cancel/result and related API routes."""
from __future__ import annotations

from unittest.mock import patch

import pytest

from app.execution import service as execution
from app.platform import connections


pytestmark = pytest.mark.integration


def _connect(project_id: str) -> None:
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


def test_write_action_approve_claim_and_result(require_db, org_with_project):
    project_id = org_with_project["project"]["id"]
    org_id = org_with_project["org"]["id"]
    _connect(project_id)
    with patch("app.execution.service.enqueue_action", return_value={"executor_available": True, "queue": "q"}):
        with patch("app.execution.service.request_wake"):
            action = execution.create_action(
                project_id=project_id,
                provider="azure",
                executable="az",
                args=["group", "create", "--name", "demo", "--location", "eastus", "--output", "json"],
                target="rg/demo",
                access_scope="write",
                expected_result="resource group exists",
                risk="creates a resource group",
                rollback="az group delete --name demo --yes",
                preflight=["group", "show", "--name", "demo", "--output", "json"],
                verify=["group", "show", "--name", "demo", "--output", "json"],
            )
    assert action["status"] == "awaiting_approval"
    with patch("app.execution.service.enqueue_action", return_value={"executor_available": True}):
        with patch("app.execution.service.request_wake"):
            approved = execution.approve_action(action["id"], "lead")
    assert approved["status"] == "queued"
    claimed = execution.claim_for_executor(action["id"], "azure", executor_org_id=org_id)
    assert claimed["credentials"]["tenant_id"] == "t"
    execution.append_event(action["id"], "stdout", {"line": "ok"})
    execution.mark_result(action["id"], "succeeded", {"stdout": "{}"}, "")
    done = execution.get_action(action["id"])
    assert done["status"] in {"succeeded", "verification_failed", "failed"}
    diag = execution.diagnose_action(action["id"])
    assert diag
    assert execution.validate_executor_org(action["id"], org_id) == org_id
    execution.validate_executor_provider(action["id"], "azure")
    with pytest.raises(ValueError):
        execution.validate_executor_provider(action["id"], "aws")
    assert execution.is_canceled(action["id"], "azure") is False


def test_cancel_queued_read_action(require_db, org_with_project):
    project_id = org_with_project["project"]["id"]
    _connect(project_id)
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
    canceled = execution.cancel_action(action["id"], "tester")
    assert canceled["status"] == "canceled"
    assert execution.is_canceled(action["id"], "azure") is True


def test_action_api_create_get_and_missing(client, org_with_project):
    headers = {"Authorization": f"Bearer {org_with_project['admin']['token']}"}
    project_id = org_with_project["project"]["id"]
    _connect(project_id)
    with patch("app.execution.service.enqueue_action", return_value={"executor_available": False}):
        with patch("app.execution.service.request_wake"):
            created = client.post(
                "/api/actions",
                json={
                    "project_id": project_id,
                    "provider": "azure",
                    "executable": "az",
                    "args": ["account", "show", "--output", "json"],
                    "target": "identity",
                    "access_scope": "read_only",
                },
                headers=headers,
            )
    assert created.status_code == 200
    action_id = created.json()["id"]
    fetched = client.get(f"/api/actions/{action_id}", headers=headers)
    assert fetched.status_code == 200
    events = client.get(f"/api/actions/{action_id}/events", headers=headers)
    assert events.status_code == 200
    diag = client.get(f"/api/actions/{action_id}/diagnostics", headers=headers)
    assert diag.status_code == 200
    missing = client.get("/api/actions/missing", headers=headers)
    assert missing.status_code == 404
    cancel = client.post(
        f"/api/actions/{action_id}/cancel",
        json={"approver": "admin"},
        headers=headers,
    )
    assert cancel.status_code in {200, 409}
