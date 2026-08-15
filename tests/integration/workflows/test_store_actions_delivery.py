"""Execution action lifecycle, delivery runs, chats, and workflow store."""
from __future__ import annotations

from unittest.mock import patch

import pytest

from app.chat import chats
from app.execution import service as execution
from app.intelligence import workflows as intel
from app.platform import delivery, memory


pytestmark = pytest.mark.integration


def test_chat_message_edit_and_history(require_db, org_with_project):
    project_id = org_with_project["project"]["id"]
    chat = chats.create_chat("Hello world", project_id=project_id)
    added = chats.add_message(chat["id"], "user", "follow up")
    history = chats.get_history(chat["id"])
    assert history[-1]["content"] == "follow up"
    loaded = chats.get_chat(chat["id"])
    assert loaded is not None
    assert loaded["messages"]
    assert chats.replace_user_message(chat["id"], added["id"], "edited") is True
    assert chats.replace_user_message(chat["id"], "missing", "x") is False
    assert chats.rename_chat(chat["id"], "New title")["title"] == "New title"
    assert chats.delete_chat(chat["id"]) is True
    assert chats.get_chat(chat["id"]) is None


def _connect_azure(project_id: str) -> None:
    from app.platform import connections

    connections.set_connection(
        project_id,
        "azure",
        "client_secret",
        {
            "tenant_id": "tenant",
            "client_id": "client",
            "client_secret": "secret",
            "subscription_id": "sub-1",
        },
    )


def test_read_action_lifecycle_with_mocked_queue(require_db, org_with_project):
    project_id = org_with_project["project"]["id"]
    _connect_azure(project_id)
    with patch(
        "app.execution.service.enqueue_action",
        return_value={"executor_available": False, "queue": "q"},
    ):
        with patch("app.execution.service.request_wake"):
            action = execution.create_action(
                project_id=project_id,
                provider="azure",
                executable="az",
                args=["account", "show", "--output", "json"],
                target="identity",
                access_scope="read_only",
                expected_result="identity json",
                risk="read only",
                rollback="n/a",
                preflight=[],
                verify=[],
            )
    assert action["id"]
    loaded = execution.get_action(action["id"])
    assert loaded["status"] in {"queued", "awaiting_approval", "pending"}
    events = execution.list_events(action["id"])
    assert isinstance(events, list)
    with pytest.raises(KeyError):
        execution.get_action("missing-action")


def test_write_action_requires_risk_and_can_be_rejected(require_db, org_with_project):
    project_id = org_with_project["project"]["id"]
    _connect_azure(project_id)
    with pytest.raises(ValueError):
        execution.create_action(
            project_id=project_id,
            provider="azure",
            executable="az",
            args=["group", "create", "--name", "x", "--location", "eastus"],
            target="rg/x",
            access_scope="write",
            expected_result="",
            risk="",
            rollback="az group delete -n x",
            preflight=["group", "show", "--name", "x"],
            verify=["group", "show", "--name", "x"],
        )
    with patch(
        "app.execution.service.enqueue_action",
        return_value={"executor_available": True},
    ):
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
    if action["status"] == "awaiting_approval":
        rejected = execution.reject_action(action["id"], "tester", "not now")
        assert rejected["status"] == "failed"


def test_delivery_run_transition_and_docs(require_db, org_with_project):
    project_id = org_with_project["project"]["id"]
    run = delivery.create_run(project_id, created_by="tester")
    assert run["stage"] == "ingest"
    assert delivery.get_run(run["id"])["id"] == run["id"]
    assert delivery.get_run("missing") is None
    listed = delivery.list_runs(project_id)
    assert any(row["id"] == run["id"] for row in listed)
    ingested = delivery.ingest_docs(run["id"], docs="# requirements\n- api", user_role="developer")
    assert ingested["artifacts"]["docs"].startswith("# requirements")
    with pytest.raises(PermissionError):
        delivery.transition(run["id"], to_stage="apply", user_role="developer")
    advanced = delivery.transition(run["id"], to_stage="architecture", user_role="developer")
    assert advanced["stage"] == "architecture"


def test_workflow_findings_dashboard_and_memory(require_db, org_with_project):
    project_id = org_with_project["project"]["id"]
    workflow = intel.create_workflow(
        project_id,
        name="Posture",
        skills=["cloud_posture", "terraform_executor"],
        objective="review",
        module="security_patch",
    )
    assert "cloud_posture" in workflow["skills"]
    run = intel.create_run(workflow["id"], trigger="manual")
    assert run is not None
    intel.mark_run_running(run["id"])
    saved = intel.save_findings(
        run["id"],
        workflow["id"],
        project_id,
        [
            {
                "title": "Public NSG",
                "severity": "high",
                "resource": "nsg-1",
                "skill": "cloud_posture",
                "module": "security_patch",
                "evidence": "0.0.0.0/0",
                "recommended_action": "restrict",
                "risk_class": "config_code_change",
                "blast_radius": "high",
                "gate_decision": "human_approval",
                "gate_label": "Human approval",
                "gate_rationale": "prod",
            }
        ],
    )
    assert saved >= 1
    intel.mark_run_succeeded(run["id"], saved)
    findings = intel.list_findings(project_id)
    assert findings
    updated = intel.update_finding_status(findings[0]["id"], "acknowledged")
    assert updated["status"] == "acknowledged"
    summary = intel.dashboard_summary(project_id)
    assert summary
    memory.remember_action(
        project_id=project_id,
        action_id="act-1",
        summary="restricted nsg",
        outcome="approved",
        payload={"skill": "cloud_posture"},
    )
    rows = memory.list_precedent(project_id, limit=5)
    assert isinstance(rows, list)
    deleted = intel.delete_workflow(workflow["id"])
    assert deleted is True
