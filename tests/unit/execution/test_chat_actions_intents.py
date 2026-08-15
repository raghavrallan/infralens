"""Chat action routing helpers and handle_turn fall-through."""
from __future__ import annotations

from unittest.mock import patch

import pytest

from app.execution import chat_actions


@pytest.mark.unit
@pytest.mark.infra
def test_handle_turn_returns_none_for_ordinary_chat():
    with patch("app.execution.chat_actions._pending_action", return_value=None):
        with patch("app.execution.chat_actions._latest_action", return_value=None):
            with patch("app.execution.chat_actions.chat_memory.get_model_context", return_value=[]):
                result = chat_actions.handle_turn(
                    "chat-1", "p1", "what is a resource group?", "read_only"
                )
    assert result is None


@pytest.mark.unit
@pytest.mark.infra
def test_handle_turn_reports_running_action_diagnostics():
    active = {
        "id": "a1",
        "status": "running",
        "command_preview": "az group create --name demo",
    }
    with patch("app.execution.chat_actions._pending_action", return_value=None):
        with patch("app.execution.chat_actions._latest_action", return_value=active):
            with patch(
                "app.execution.chat_actions.action_diagnostic_context",
                return_value="still running",
            ):
                result = chat_actions.handle_turn(
                    "chat-1", "p1", "why is this taking so long?", "read_only"
                )
    assert result is not None
    assert result["event_type"] == "action_diagnostic"


@pytest.mark.unit
def test_provider_status_text_lists_disconnected_providers():
    with patch(
        "app.execution.chat_actions.provider_status",
        return_value=[
            {"provider": "azure", "connected": False, "ready": False, "detail": "missing", "actions_available": False},
            {"provider": "github", "connected": True, "ready": True, "detail": "ok", "actions_available": True},
        ],
    ):
        text = chat_actions.provider_status_text("p1", "read_only")
    assert "azure" in text.lower() or "GitHub" in text or text


@pytest.mark.unit
def test_intent_helpers_and_specs():
    assert chat_actions._debug_intent("why did it fail last night")
    assert chat_actions._cicd_intent("github actions failed on main")
    assert chat_actions._delete_requested("please delete the resource group")
    assert not chat_actions._delete_requested("list resource groups")
    spec = chat_actions._resource_group_spec("demo", "eastus", "sub")
    assert spec["args"][0] == "group"
    delete = chat_actions._resource_group_delete_spec("demo", "sub")
    assert "delete" in delete["args"]
    assert chat_actions._region_from_message("create it in westus2") in {"westus2", "eastus", ""}
    assert chat_actions._is_compound_request(
        "create resource group testing in eastus and a vnet"
    )
    assert chat_actions._contains_resource_group_operation(
        {"args": ["group", "create", "--name", "x"]}
    )
    assert chat_actions._contains_vnet_operation(
        {"args": ["network", "vnet", "create", "--name", "v"]}
    )
    with patch("app.execution.chat_actions.provider_status_text", return_value="status"):
        held = chat_actions._scope_required_reply(
            spec, "p1", "read_only", "ask_approval", "Need write scope"
        )
    assert held["required_action_scope"] == "write"
