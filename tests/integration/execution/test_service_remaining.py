"""Remaining execution-service branches: compound, terraform, github, diagnose, results."""
from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import patch

import pytest

from app.execution import service as execution
from app.platform import connections
from app.tenancy import projects


pytestmark = pytest.mark.integration


def _connect_azure(project_id: str) -> None:
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


def _connect_github(project_id: str) -> None:
    connections.set_connection(
        project_id,
        "github",
        "token",
        {"token": "ghp_testtoken", "username": "acme"},
    )


def test_create_action_rejects_invalid_access_level(require_db, org_with_project):
    project_id = org_with_project["project"]["id"]
    _connect_azure(project_id)
    with pytest.raises(ValueError, match="Unsupported access level"):
        execution.create_action(
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
            access_level="dangerous",
        )


def test_compound_read_action_and_incomplete_result(require_db, org_with_project):
    project_id = org_with_project["project"]["id"]
    _connect_azure(project_id)
    steps = [
        {
            "provider": "azure",
            "executable": "az",
            "args": ["account", "show", "--output", "json"],
            "target": "identity",
            "access_scope": "read_only",
            "expected_result": "account json",
        },
        {
            "provider": "azure",
            "executable": "az",
            "args": ["group", "list", "--output", "json"],
            "target": "groups",
            "access_scope": "read_only",
            "skip_if_exists": True,
            "preflight_expect": "false",
        },
    ]
    with patch("app.execution.service.enqueue_action", return_value={"executor_available": False, "queue": "q"}):
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
                steps=steps,
                why="inventory",
                blast_radius="low",
                degrade_plan="retry later",
            )
    assert action["status"] == "queued"
    assert action["operation"].get("steps")
    with pytest.raises(ValueError, match="Invalid terminal"):
        execution.mark_result(action["id"], "running", {})
    execution.mark_result(action["id"], "succeeded", {"stdout": "partial"})
    done = execution.get_action(action["id"])
    assert done["status"] == "failed"
    assert "incomplete compound" in (done.get("error") or "").lower()


def test_compound_step_provider_mismatch_is_rejected(require_db, org_with_project):
    project_id = org_with_project["project"]["id"]
    _connect_azure(project_id)
    with pytest.raises(ValueError, match="Compound actions"):
        execution.create_action(
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
            steps=[
                {
                    "provider": "aws",
                    "executable": "aws",
                    "args": ["sts", "get-caller-identity"],
                    "access_scope": "read_only",
                }
            ],
        )


def test_terraform_requires_cloud_connection_and_valid_provider(require_db, org_with_project):
    project_id = org_with_project["project"]["id"]
    with pytest.raises(ValueError, match="cloud_provider"):
        execution.create_action(
            project_id=project_id,
            provider="terraform",
            executable="terraform",
            args=["plan"],
            target="stack",
            access_scope="read_only",
            expected_result="plan",
            risk="",
            rollback="n/a",
            preflight=[],
            verify=[],
            cloud_provider="gcp",
        )
    with pytest.raises(ValueError, match="No azure connection"):
        execution.create_action(
            project_id=project_id,
            provider="terraform",
            executable="terraform",
            args=["plan"],
            target="stack",
            access_scope="read_only",
            expected_result="plan",
            risk="",
            rollback="n/a",
            preflight=[],
            verify=[],
            cloud_provider="azure",
        )
    _connect_azure(project_id)
    with patch("app.execution.service.enqueue_action", return_value={"executor_available": True}):
        with patch("app.execution.service.request_wake"):
            planned = execution.create_action(
                project_id=project_id,
                provider="terraform",
                executable="terraform",
                args=["plan"],
                target="stack",
                access_scope="read_only",
                expected_result="plan",
                risk="",
                rollback="n/a",
                preflight=[],
                verify=[],
                cloud_provider="azure",
            )
    assert planned["provider"] == "terraform"
    apply_action = execution.create_action(
        project_id=project_id,
        provider="terraform",
        executable="terraform",
        args=["apply"],
        target="stack",
        access_scope="write",
        expected_result="applied",
        risk="changes live infra",
        rollback="terraform destroy targeted resources now",
        preflight=["plan"],
        verify=["show"],
        cloud_provider="azure",
    )
    assert apply_action["status"] == "awaiting_approval"


def test_github_target_must_be_mapped(require_db, org_with_project):
    project_id = org_with_project["project"]["id"]
    _connect_github(project_id)
    projects.set_repos(project_id, ["acme/app"])
    with pytest.raises(ValueError, match="outside the repositories"):
        execution.create_action(
            project_id=project_id,
            provider="github",
            executable="gh",
            args=["repo", "view", "acme/other"],
            target="acme/other",
            access_scope="read_only",
            expected_result="ok",
            risk="",
            rollback="n/a",
            preflight=[],
            verify=[],
        )
    with patch("app.execution.service.enqueue_action", return_value={"executor_available": True}):
        with patch("app.execution.service.request_wake"):
            ok = execution.create_action(
                project_id=project_id,
                provider="github",
                executable="gh",
                args=["repo", "view", "acme/app"],
                target="acme/app",
                access_scope="read_only",
                expected_result="ok",
                risk="",
                rollback="n/a",
                preflight=[],
                verify=[],
            )
    assert ok["target"] == "acme/app"


def test_full_access_requires_two_confirmations(require_db, org_with_project):
    project_id = org_with_project["project"]["id"]
    org_id = org_with_project["org"]["id"]
    _connect_azure(project_id)
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
        access_level="full_access",
    )
    first = execution.approve_action(action["id"], "lead")
    assert first["status"] == "awaiting_approval"
    assert first["approval"]["confirmation_count"] == 1
    with patch("app.execution.service.enqueue_action", return_value={"executor_available": True}):
        with patch("app.execution.service.request_wake"):
            second = execution.approve_action(action["id"], "lead")
    assert second["status"] == "queued"
    claimed = execution.claim_for_executor(second["id"], "azure", executor_org_id=org_id)
    assert claimed["credentials"]["tenant_id"] == "t"


def test_diagnose_queued_without_executor_and_list_events_missing(require_db, org_with_project):
    project_id = org_with_project["project"]["id"]
    _connect_azure(project_id)
    with patch("app.execution.service.enqueue_action", return_value={"executor_available": False, "queue": "q"}):
        with patch("app.execution.service.request_wake", side_effect=RuntimeError("wake failed")):
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
    with patch(
        "app.execution.service.queue_snapshot",
        return_value={"executor_available": False, "queue": "q", "queue_depth": 1},
    ):
        with patch(
            "app.execution.service.org_executor_settings.get_settings",
            return_value={"actual_state": "scaled_to_zero", "mode": "on_demand"},
        ):
            diag = execution.diagnose_action(action["id"])
    assert diag["status"] == "queued"
    assert "scaled to zero" in diag["message"].lower() or "waiting" in diag["message"].lower()
    with pytest.raises(KeyError):
        execution.list_events("missing-action")
    execution._record_dispatch_diagnostic("missing-action", {"queue": "q"})


def test_reject_then_cannot_approve(require_db, org_with_project):
    project_id = org_with_project["project"]["id"]
    _connect_azure(project_id)
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
    rejected = execution.reject_action(action["id"], "lead", "not now")
    assert rejected["status"] == "failed"
    with pytest.raises(ValueError, match="not awaiting"):
        execution.approve_action(action["id"], "lead")
    with pytest.raises(ValueError, match="not awaiting"):
        execution.reject_action(action["id"], "lead", "again")


def test_verification_failed_delete_is_reconciled(require_db, org_with_project):
    project_id = org_with_project["project"]["id"]
    _connect_azure(project_id)
    action = execution.create_action(
        project_id=project_id,
        provider="azure",
        executable="az",
        args=["group", "delete", "--name", "demo", "--yes", "--output", "json"],
        target="rg/demo",
        access_scope="write",
        expected_result="group gone",
        risk="deletes a resource group",
        rollback="az group create --name demo --location eastus",
        preflight=["group", "show", "--name", "demo", "--output", "json"],
        verify=["group", "show", "--name", "demo", "--output", "json"],
    )
    with patch("app.execution.service.enqueue_action", return_value={"executor_available": True}):
        with patch("app.execution.service.request_wake"):
            execution.approve_action(action["id"], "lead")
    execution.mark_result(
        action["id"],
        "verification_failed",
        {
            "verification": {
                "returncode": 3,
                "stdout": "",
                "stderr": "ResourceGroupNotFound: could not be found",
                "timed_out": False,
            }
        },
        "verify failed",
    )
    reconciled = execution.get_action(action["id"])
    assert reconciled["status"] == "succeeded"


def test_claim_and_validate_org_errors(require_db, org_with_project):
    project_id = org_with_project["project"]["id"]
    org_id = org_with_project["org"]["id"]
    _connect_azure(project_id)
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
    with pytest.raises(ValueError, match="different provider"):
        execution.claim_for_executor(action["id"], "aws", executor_org_id=org_id)
    with pytest.raises(ValueError, match="org id is required"):
        execution.claim_for_executor(action["id"], "azure", executor_org_id="")
    with pytest.raises(ValueError, match="does not match"):
        execution.claim_for_executor(action["id"], "azure", executor_org_id="other-org")
    with pytest.raises(ValueError, match="org id is required"):
        execution.validate_executor_org(action["id"], "")
    with pytest.raises(KeyError):
        execution.validate_executor_org("missing", org_id)
    with pytest.raises(KeyError):
        execution.is_canceled("missing", "azure")
    with pytest.raises(KeyError):
        execution.append_event("missing", "stdout", {})
    canceled = execution.cancel_action(action["id"], "tester")
    assert canceled["status"] == "canceled"
    execution.mark_result(action["id"], "succeeded", {"stdout": "late"})
    still = execution.get_action(action["id"])
    assert still["status"] == "canceled"
    naive = datetime.now().replace(tzinfo=None)
    with patch("app.execution.service._now", return_value=datetime.now(timezone.utc)):
        with patch(
            "app.execution.service.queue_snapshot",
            return_value={"executor_available": True, "queue": "q", "queue_depth": 0},
        ):
            diag = execution.diagnose_action(action["id"])
    assert diag["status"] == "canceled"
    _ = naive
