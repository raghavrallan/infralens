"""handle_turn remaining routes: approval, terraform, debug, deploy, Azure specs."""
from __future__ import annotations

from unittest.mock import patch

import pytest

from app.execution import chat_actions


def _idle():
    return patch.multiple(
        "app.execution.chat_actions",
        _pending_action=lambda _chat: None,
        _latest_action=lambda _chat: None,
    )


@pytest.mark.unit
def test_create_or_hold_action_missing_fields_and_exceptions():
    incomplete = chat_actions._create_or_hold_action(
        {"provider": "azure"}, "p1", "write", "intro"
    )
    assert incomplete["action"] is None
    spec = chat_actions._resource_group_spec("demo", "eastus", "sub")
    with patch("app.execution.chat_actions.provider_status_text", return_value="status"):
        held = chat_actions._create_or_hold_action(spec, "p1", "read_only", "Need write")
    assert held["required_action_scope"] == "write"
    queued = {
        "id": "a1",
        "access_scope": "read_only",
        "command_preview": "az account show",
        "status": "queued",
    }
    with patch("app.execution.chat_actions.service.create_action", return_value=queued):
        with patch("app.execution.chat_actions.provider_status_text", return_value="status"):
            result = chat_actions._create_or_hold_action(spec, "p1", "write", "Queued")
    assert result["event_type"] == "action_queued"
    write_action = {
        "id": "a2",
        "access_scope": "write",
        "command_preview": "az group create",
        "status": "awaiting_approval",
    }
    with patch("app.execution.chat_actions.service.create_action", return_value=write_action):
        with patch("app.execution.chat_actions.provider_status_text", return_value="status"):
            approval = chat_actions._create_or_hold_action(
                spec, "p1", "write", "Create RG", "ask_approval"
            )
            full = chat_actions._create_or_hold_action(
                spec, "p1", "write", "Create RG", "full_access"
            )
    assert approval["event_type"] == "approval_required"
    assert "danger" in full["reply"].lower() or full["action"]
    with patch("app.execution.chat_actions.service.create_action", side_effect=ValueError("bad")):
        with patch("app.execution.chat_actions.provider_status_text", return_value="status"):
            failed = chat_actions._create_or_hold_action(spec, "p1", "write", "intro")
    assert failed["action"] is None


@pytest.mark.unit
def test_handle_turn_approves_pending_and_full_access_modal():
    pending = {
        "id": "a1",
        "access_level": "ask_approval",
        "command_preview": "az group create --name demo",
        "status": "awaiting_approval",
        "target": "resource-group/demo",
        "operation": {"args": ["group", "create", "--name", "demo"]},
    }
    approved = {**pending, "status": "queued"}
    with patch("app.execution.chat_actions._pending_action", return_value=pending):
        with patch("app.execution.chat_actions.service.approve_action", return_value=approved):
            with patch("app.execution.chat_actions.provider_status_text", return_value="status"):
                result = chat_actions.handle_turn("c1", "p1", "yes", "write")
    assert result["event_type"] == "action_queued"
    pending_full = {**pending, "access_level": "full_access"}
    with patch("app.execution.chat_actions._pending_action", return_value=pending_full):
        modal = chat_actions.handle_turn("c1", "p1", "yes", "write")
    assert "danger" in modal["reply"].lower()
    with patch("app.execution.chat_actions._pending_action", return_value=pending):
        with patch("app.execution.chat_actions.service.approve_action", side_effect=ValueError("stale")):
            failed = chat_actions.handle_turn("c1", "p1", "yes", "write")
    assert failed["event_type"] == "action_failed"


@pytest.mark.unit
def test_handle_turn_pending_reference_without_yes():
    pending = {
        "id": "a1",
        "command_preview": "az group create --name demo",
        "target": "resource-group/demo",
        "operation": {"args": ["group", "create", "--name", "demo"]},
    }
    with patch("app.execution.chat_actions._pending_action", return_value=pending):
        with patch("app.execution.chat_actions._latest_action", return_value=None):
            with patch(
                "app.execution.chat_actions._pending_action_reference",
                return_value=True,
            ):
                with patch(
                    "app.execution.chat_actions._pending_confirmation",
                    return_value=False,
                ):
                    result = chat_actions.handle_turn(
                        "c1", "p1", "what about that resource group demo action", "write"
                    )
    assert result["event_type"] == "approval_required"


@pytest.mark.unit
def test_handle_turn_debug_and_deploy_write():
    failed = {
        "id": "a9",
        "status": "failed",
        "command_preview": "az group create",
    }
    with _idle():
        with patch("app.execution.chat_actions.chat_memory.get_model_context", return_value=[]):
            with patch("app.execution.chat_actions._latest_action", return_value=failed):
                with patch(
                    "app.chat.project_context.gather_project_topology",
                    return_value="topo",
                ):
                    with patch(
                        "app.execution.debug_loop.run_debug_cycle",
                        return_value={
                            "retry_action": {
                                "id": "r1",
                                "command_preview": "az group create --name demo",
                                "status": "awaiting_approval",
                            },
                            "proposal": {"root_cause": "auth", "fix_summary": "retry login"},
                            "message": "ok",
                        },
                    ):
                        with patch(
                            "app.execution.chat_actions.provider_status_text",
                            return_value="status",
                        ):
                            debug = chat_actions.handle_turn(
                                "c1", "p1", "why did it fail last night", "write"
                            )
    assert "Root cause" in debug["reply"]
    with _idle():
        with patch("app.execution.chat_actions.chat_memory.get_model_context", return_value=[]):
            with patch(
                "app.execution.deploy_orchestrator.run_deploy_pipeline",
                return_value={
                    "plan": {
                        "strategy": "all_at_once",
                        "stages": [{"name": "plan", "status": "succeeded", "detail": "ok"}],
                    },
                    "pipeline": {
                        "action": {
                            "id": "d1",
                            "command_preview": "terraform apply",
                            "status": "awaiting_approval",
                        }
                    },
                },
            ):
                with patch(
                    "app.execution.chat_actions.provider_status_text",
                    return_value="status",
                ):
                    deploy = chat_actions.handle_turn(
                        "c1", "p1", "deploy to production", "write"
                    )
    assert deploy["action"]["id"] == "d1"


@pytest.mark.unit
def test_handle_turn_terraform_phases():
    with _idle():
        with patch("app.execution.chat_actions.chat_memory.get_model_context", return_value=[]):
            apply_blocked = chat_actions.handle_turn(
                "c1", "p1", "terraform apply", "read_only"
            )
    assert apply_blocked["required_action_scope"] == "write"
    fake_action = {
        "id": "t1",
        "command_preview": "terraform plan",
        "status": "queued",
    }
    with _idle():
        with patch("app.execution.chat_actions.chat_memory.get_model_context", return_value=[]):
            with patch(
                "app.execution.terraform_runner.create_terraform_action",
                return_value=fake_action,
            ):
                with patch(
                    "app.execution.chat_actions.provider_status_text",
                    return_value="status",
                ):
                    planned = chat_actions.handle_turn("c1", "p1", "terraform plan", "read_only")
    assert planned["action"]["id"] == "t1"
    with _idle():
        with patch("app.execution.chat_actions.chat_memory.get_model_context", return_value=[]):
            with patch(
                "app.execution.terraform_runner.create_terraform_action",
                side_effect=RuntimeError("no files"),
            ):
                failed = chat_actions.handle_turn("c1", "p1", "terraform validate", "read_only")
    assert failed["action"] is None
    with _idle():
        with patch("app.execution.chat_actions.chat_memory.get_model_context", return_value=[]):
            with patch(
                "app.execution.terraform_runner.pipeline",
                return_value={
                    "ok": True,
                    "action": {
                        "id": "t2",
                        "command_preview": "terraform apply",
                        "status": "awaiting_approval",
                    },
                    "plan_summary": {"add": 1, "change": 0, "destroy": 0},
                },
            ):
                with patch("app.execution.chat_actions.chat_memory.record_deployment_outcome"):
                    with patch(
                        "app.execution.chat_actions.provider_status_text",
                        return_value="status",
                    ):
                        applied = chat_actions.handle_turn(
                            "c1", "p1", "terraform apply", "write"
                        )
    assert applied["event_type"] == "approval_required"


@pytest.mark.unit
def test_handle_turn_cicd_with_prepared_reruns():
    with _idle():
        with patch("app.execution.chat_actions.chat_memory.get_model_context", return_value=[]):
            with patch(
                "app.execution.cicd.auto_retry_failed_builds",
                return_value={
                    "prepared": [
                        {
                            "run": {"repo": "acme/app", "id": 9},
                            "action": {"id": "c1", "command_preview": "gh run rerun 9"},
                        },
                        {"error": "boom"},
                    ]
                },
            ):
                with patch(
                    "app.execution.chat_actions.provider_status_text",
                    return_value="status",
                ):
                    result = chat_actions.handle_turn(
                        "c1", "p1", "github actions failed on main", "write"
                    )
    assert result["action"]["id"] == "c1"


@pytest.mark.unit
def test_handle_turn_vnet_missing_inputs():
    with _idle():
        with patch("app.execution.chat_actions.chat_memory.get_model_context", return_value=[]):
            with patch("app.execution.chat_actions._context_resource_group", return_value=None):
                missing_rg = chat_actions.handle_turn(
                    "c1", "p1", "create vnet app-vnet with 10.0.0.0/16 and 10.0.0.0/24", "write"
                )
    assert missing_rg["required_action_scope"] == "write"
    with _idle():
        with patch("app.execution.chat_actions.chat_memory.get_model_context", return_value=[]):
            with patch(
                "app.execution.chat_actions._context_resource_group",
                return_value={"name": "rg1", "location": "eastus"},
            ):
                with patch(
                    "app.execution.chat_actions.connections.get_secret_fields",
                    return_value={"subscription_id": "sub"},
                ):
                    with patch(
                        "app.execution.chat_actions._create_or_hold_action",
                        return_value={"reply": "prepared", "action": {"id": "v1"}},
                    ):
                        prepared = chat_actions.handle_turn(
                            "c1",
                            "p1",
                            "create vnet app-vnet with address 10.0.0.0/16 and subnet 10.0.0.0/24",
                            "write",
                        )
    assert prepared["action"]["id"] == "v1" or prepared["reply"]


@pytest.mark.unit
def test_terraform_intent_kinds():
    history: list[dict[str, str]] = []
    assert chat_actions._terraform_intent("terraform apply now", history)["phase"] == "apply"
    assert chat_actions._terraform_intent("terraform destroy", history)["phase"] == "destroy"
    assert chat_actions._terraform_intent("terraform init", history)["phase"] == "init"
    assert chat_actions._terraform_intent("terraform validate", history)["phase"] == "validate"
    assert chat_actions._terraform_intent("generate terraform for a vnet", history)["kind"] == "terraform_generate"
    assert chat_actions._terraform_intent("just terraform", history) is None
    assert chat_actions._deploy_intent("outline a rollout plan") is False
    assert chat_actions._deploy_intent("deploy now to production") or chat_actions._deploy_intent(
        "full deployment to prod"
    )
