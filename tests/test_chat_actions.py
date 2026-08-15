import unittest
import json
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from app.execution.action_planner import plan_action
from app.execution.chat_actions import (
    _pending_confirmation,
    _context_nsg_name,
    _context_resource_group,
    action_diagnostic_context,
    handle_turn,
    _resource_group_delete_spec,
    _resource_group_nsg_spec,
    _resource_group_vnet_spec,
    _resource_group_request,
    _pending_action_reference,
    _vnet_request,
    provider_status,
    provider_status_text,
)
from app.execution.action_planner import (
    looks_like_action,
    looks_like_diagnostic,
    looks_like_scope_clarification,
)


@pytest.mark.infra
class ChatActionParsingTests(unittest.TestCase):
    def test_resource_group_name_and_region_are_extracted(self):
        parsed = _resource_group_request("Create me a new resource group in Azure named testing in eastus")
        self.assertEqual(parsed, {"name": "testing", "location": "eastus"})

    def test_missing_region_is_not_guessed_from_the_provider_name(self):
        parsed = _resource_group_request("Create me a new resource group in Azure name testing")
        self.assertEqual(parsed, {"name": "testing", "location": ""})

    def test_child_resource_name_is_not_mistaken_for_resource_group_name(self):
        parsed = _resource_group_request(
            "create a storage account name storage1 inside this resource group"
        )
        self.assertIsNone(parsed)

    def test_region_parser_does_not_capture_the_word_after_region(self):
        parsed = _resource_group_request(
            "Create resource group testing in eastus region and also document it"
        )
        self.assertEqual(parsed, {"name": "testing", "location": "eastus"})

    def test_compound_vnet_request_bypasses_resource_group_shortcut(self):
        parsed = _resource_group_request(
            "Create resource group testing in eastus and a VNet with a default subnet"
        )
        self.assertIsNone(parsed)

    def test_compound_vnet_request_routes_to_structured_action_planner(self):
        self.assertTrue(
            looks_like_action(
                "create resource group testing in eastus and a vnet with a default subnet",
                [],
            )
        )

    def test_unrelated_questions_do_not_create_actions(self):
        self.assertIsNone(_resource_group_request("Which Azure providers are connected?"))

    def test_drift_posture_review_is_diagnostic_not_action(self):
        msg = (
            "Review our current Azure infrastructure posture against what's in our "
            "GitHub repos. Call out drift, missing IaC, and risky public exposure."
        )
        self.assertTrue(looks_like_diagnostic(msg))
        self.assertFalse(looks_like_action(msg, []))
        # Follow-ups must not become actions via prior chat history.
        history = [
            {"role": "user", "content": msg},
            {
                "role": "assistant",
                "content": "Which GitHub repository should I compare against Azure?",
            },
        ]
        self.assertFalse(looks_like_action("everything broo present in code", history))
        self.assertTrue(looks_like_diagnostic("every service present in the code"))
        self.assertTrue(
            looks_like_diagnostic("evrything bro just check all of it", history)
        )
        self.assertTrue(
            looks_like_diagnostic(
                "idk which repo just use whatever is mapped", history
            )
        )
        self.assertFalse(
            looks_like_action("same for the code too not just cloud", history)
        )
        self.assertTrue(
            looks_like_scope_clarification(
                "Which GitHub repository or repositories should I compare against Azure, "
                "and which Azure scope should I assess (subscription, resource group, or "
                "specific resource)?"
            )
        )

    @patch("app.execution.chat_actions.action_planner.plan_action")
    @patch("app.execution.chat_actions.chats.get_chat", return_value={"messages": []})
    def test_diagnostic_review_skips_action_planner(self, _get_chat, plan_action):
        result = handle_turn(
            "chat-1",
            "project-1",
            "Review our Azure infrastructure posture against GitHub for drift",
            "read_only",
        )
        self.assertIsNone(result)
        plan_action.assert_not_called()

    @patch(
        "app.execution.chat_actions.action_planner.plan_action",
        return_value={
            "kind": "clarification",
            "question": (
                "Which GitHub repository or repositories should I compare against Azure, "
                "and which Azure scope should I assess (subscription, resource group, or "
                "specific resource)?"
            ),
            "needs": ["repository", "azure_scope"],
            "operation": {},
            "operations": [],
        },
    )
    @patch("app.execution.chat_actions.chats.get_chat", return_value={"messages": []})
    def test_scope_clarification_falls_through_to_chat(self, _get_chat, _plan):
        # Message itself is not classified diagnostic ("create" + soft terms),
        # but the planner's scope interview must still fall through.
        with patch(
            "app.execution.chat_actions.action_planner.looks_like_diagnostic",
            return_value=False,
        ):
            with patch(
                "app.execution.chat_actions.action_planner.looks_like_action",
                return_value=True,
            ):
                result = handle_turn(
                    "chat-1",
                    "project-1",
                    "check my azure infrastructure and github",
                    "read_only",
                )
        self.assertIsNone(result)

    @patch("app.execution.chat_actions.action_planner.plan_action", return_value=None)
    @patch("app.execution.chat_actions.chats.get_chat", return_value={"messages": []})
    def test_normal_agent_turn_falls_back_to_chat(self, _get_chat, _plan_action):
        self.assertIsNone(handle_turn("chat-1", "project-1", "hello", "read_only"))

    @patch(
        "app.execution.chat_actions.connections.get_secret_fields",
        return_value={"subscription_id": "sub-1"},
    )
    @patch("app.execution.chat_actions.service.create_action")
    @patch("app.execution.chat_actions.chats.get_chat", return_value={"messages": []})
    def test_complete_resource_group_request_bypasses_generic_subscription_question(
        self, _get_chat, create_action, _secret_fields
    ):
        create_action.return_value = {
            "id": "action-1",
            "access_scope": "write",
            "status": "awaiting_approval",
            "command_preview": "az group create --name testing_eq --location eastus --output json",
        }

        result = handle_turn(
            "chat-1",
            "default",
            "create me a new resource group name testing_eq in eastus region",
            "write",
        )

        self.assertIsNotNone(result)
        self.assertIn("testing_eq", result["reply"])
        self.assertIn("eastus", result["reply"])
        self.assertNotIn("Which Azure subscription", result["reply"])
        create_action.assert_called_once()

    def test_generic_delete_confirmation_uses_pending_target(self):
        action = {
            "target": "subscription/sub/resource-group/testing-codex-flow-3",
            "operation": {"args": ["group", "delete", "--name", "testing-codex-flow-3"]},
        }
        self.assertTrue(_pending_confirmation("delete this", action))
        self.assertTrue(_pending_confirmation("yes delete this testing-codex-flow-3", action))
        self.assertFalse(_pending_confirmation("delete another-group", action))

    def test_confirmed_is_a_valid_generic_confirmation(self):
        action = {
            "target": "subscription/sub/resource-group/testing",
            "operation": {"args": ["group", "delete", "--name", "testing"]},
        }
        self.assertTrue(_pending_confirmation("confirmed", action))

    def test_pending_action_reference_distinguishes_new_request_from_reuse(self):
        action = {"target": "subscription/sub/resource-group/testing_eq"}
        self.assertTrue(_pending_action_reference("create it", action))
        self.assertFalse(
            _pending_action_reference(
                "now create a vnet name test-vnet inside this resource group with default subnet",
                action,
            )
        )

    def test_delete_spec_uses_absence_as_the_postcondition(self):
        spec = _resource_group_delete_spec("testing", "sub-1")
        self.assertEqual(spec["args"][1], "delete")
        self.assertEqual(spec["verify"][1], "show")
        self.assertIn("deletion", spec["expected_result"])

    def test_nsg_request_is_ordered_after_resource_group(self):
        spec = _resource_group_nsg_spec("testing", "eastus", "test-demo-nsg", "sub-1")
        self.assertEqual(len(spec["steps"]), 2)
        self.assertEqual(spec["steps"][0]["args"][:2], ["group", "create"])
        self.assertEqual(spec["steps"][1]["args"][:3], ["network", "nsg", "create"])
        self.assertEqual(spec["steps"][1]["args"][3:5], ["--resource-group", "testing"])

    def test_vnet_request_extracts_name_and_requires_explicit_ranges(self):
        parsed = _vnet_request(
            "now create a vnet name test-vnet inside this resource group with default subnet"
        )
        self.assertEqual(parsed, {"name": "test-vnet", "address_prefix": "", "subnet_prefix": ""})

    def test_vnet_spec_keeps_resource_group_as_an_ordered_parent(self):
        spec = _resource_group_vnet_spec(
            "testing_eq", "eastus", "test-vnet", "10.0.0.0/16", "10.0.0.0/24", "sub-1"
        )
        self.assertEqual(len(spec["steps"]), 2)
        self.assertEqual(spec["steps"][0]["args"][:2], ["group", "create"])
        self.assertEqual(spec["steps"][1]["args"][:3], ["network", "vnet", "create"])
        self.assertIn("--subnet-name", spec["steps"][1]["args"])
        self.assertIn("default", spec["steps"][1]["args"])

    @patch("app.execution.chat_actions.chats.get_chat")
    def test_vnet_followup_does_not_repeat_the_resource_group_action(self, get_chat):
        get_chat.return_value = {
            "messages": [
                {
                    "role": "user",
                    "content": "create me a new resource group name testing_eq in eastus region",
                },
                {
                    "role": "assistant",
                    "content": "az group create --name testing_eq --location eastus --output json",
                },
            ]
        }
        result = handle_turn(
            "chat-1",
            "default",
            "now create a vnet name test-vnet inside this resource group with default subnet",
            "write",
        )
        self.assertIsNotNone(result)
        self.assertIn("address space", result["reply"])
        self.assertNotIn("az group create", result["reply"])

    @patch("app.execution.chat_actions.service.get_action")
    @patch("app.execution.chat_actions.chats.get_chat")
    def test_vnet_followup_does_not_reuse_pending_parent_action(self, get_chat, get_action):
        get_chat.return_value = {
            "messages": [
                {
                    "role": "assistant",
                    "content": "az group create --name testing_eq --location eastus --output json",
                    "meta": {"action_id": "parent-action"},
                }
            ]
        }
        get_action.return_value = {
            "id": "parent-action",
            "status": "awaiting_approval",
            "target": "subscription/sub/resource-group/testing_eq",
            "command_preview": "az group create --name testing_eq --location eastus --output json",
            "operation": {"args": ["group", "create", "--name", "testing_eq"]},
        }
        result = handle_turn(
            "chat-1",
            "project-1",
            "now create a vnet name test-vnet inside this resource group with default subnet",
            "write",
        )
        self.assertIsNotNone(result)
        self.assertIn("address space", result["reply"])
        self.assertNotIn("already prepared", result["reply"])

    @patch("app.execution.chat_actions.chats.get_chat")
    def test_vnet_range_followup_recovers_vnet_name(self, get_chat):
        get_chat.return_value = {
            "messages": [
                {"role": "user", "content": "create resource group testing_eq in eastus"},
                {"role": "user", "content": "create a vnet named test-vnet with default subnet"},
            ]
        }
        parsed = _vnet_request("create the VNet with 10.0.0.0/16 and 10.0.0.0/24")
        self.assertEqual(parsed["name"], "")
        self.assertEqual(parsed["address_prefix"], "10.0.0.0/16")
        self.assertEqual(parsed["subnet_prefix"], "10.0.0.0/24")
        self.assertEqual(_context_resource_group("chat-1"), {"name": "testing_eq", "location": "eastus"})

    @patch("app.execution.chat_actions.chats.get_chat")
    def test_nsg_followup_recovers_parent_from_prior_turn(self, get_chat):
        get_chat.return_value = {
            "messages": [
                {
                    "role": "user",
                    "content": (
                        "create a resource group in azure name testing in eastus "
                        "and also create an nsg in the same resource group"
                    ),
                },
                {"role": "user", "content": "test-demo-nsg"},
            ]
        }
        self.assertEqual(_context_resource_group("chat-1"), {"name": "testing", "location": "eastus"})
        self.assertEqual(_context_nsg_name("chat-1"), "test-demo-nsg")

    @patch("app.execution.chat_actions.connections.all_status")
    def test_provider_status_is_project_scoped_and_ui_controlled(self, all_status):
        all_status.return_value = [
            {"provider": "azure", "connected": True, "identity": "client-id"},
            {"provider": "aws", "connected": False},
            {"provider": "github", "connected": True, "identity": "user"},
        ]
        status = provider_status("project-1", "write")
        self.assertEqual([item["action_scope"] for item in status], ["write"] * 3)
        self.assertTrue(status[0]["actions_available"])
        self.assertFalse(status[1]["actions_available"])
        text = provider_status_text("project-1", "write")
        self.assertIn("write actions enabled for this request", text)
        self.assertIn("AWS: not connected", text)

    @patch("app.execution.action_planner.azure_client.chat")
    def test_structured_planner_returns_provider_operation(self, chat):
        operation = {
            "provider": "azure",
            "executable": "az",
            "args": ["containerapp", "show", "--name", "api", "--resource-group", "testing", "--output", "json"],
            "target": "resource-group/testing/container-app/api",
            "access_scope": "read_only",
            "expected_result": "The container app is returned.",
            "risk": "Read-only inspection.",
            "rollback": "Not applicable.",
            "preflight": [],
            "preflight_expect": "",
            "verify": [],
        }
        chat.return_value = SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps({"kind": "action", "question": "", "needs": [], "operation": operation})))]
        )
        planned = plan_action("show the Azure container app api", [{"role": "user", "content": "show the Azure container app api"}], "Azure connected")
        self.assertEqual(planned["kind"], "action")
        self.assertEqual(planned["operation"]["executable"], "az")

    @patch("app.execution.action_planner.azure_client.chat")
    def test_structured_planner_receives_compact_chat_memory(self, chat):
        operation = {
            "provider": "azure",
            "executable": "az",
            "args": ["group", "show", "--name", "testing", "--output", "json"],
            "target": "resource-group/testing",
            "access_scope": "read_only",
            "expected_result": "The resource group is returned.",
            "risk": "Read-only inspection.",
            "rollback": "Not applicable.",
            "preflight": [],
            "preflight_expect": "",
            "verify": [],
        }
        chat.return_value = SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps({
                "kind": "action", "question": "", "needs": [], "operation": operation
            })))]
        )
        history = [
            {
                "role": "system",
                "content": (
                    "CHAT MEMORY (same chat and project):\n"
                    "References:\n- resource-group/testing\n- region=eastus"
                ),
            },
            {"role": "user", "content": "show it"},
        ]

        planned = plan_action("show it", history, "Azure connected")

        self.assertEqual(planned["kind"], "action")
        self.assertEqual(len(planned["operations"]), 1)
        prompt = chat.call_args.args[0][1]["content"]
        self.assertIn("CURRENT USER REQUEST (authoritative", prompt)
        self.assertIn("resource-group/testing", prompt)
        self.assertIn("region=eastus", prompt)

    @patch("app.execution.chat_actions._latest_action")
    def test_unrelated_request_does_not_receive_old_action_diagnostics(self, latest_action):
        self.assertEqual(
            action_diagnostic_context("chat-1", "show me the CPU metrics"),
            "",
        )
        latest_action.assert_not_called()

    @patch("app.execution.action_planner.azure_client.chat")
    def test_structured_planner_receives_recent_turn_context(self, chat):
        operation = {
            "provider": "azure",
            "executable": "az",
            "args": ["group", "show", "--name", "testing_eq", "--output", "json"],
            "target": "resource-group/testing_eq",
            "access_scope": "read_only",
            "expected_result": "The resource group is returned.",
            "risk": "Read-only inspection.",
            "rollback": "Not applicable.",
            "preflight": [],
            "preflight_expect": "",
            "verify": [],
        }
        chat.return_value = SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps({
                "kind": "action", "question": "", "needs": [], "operation": operation
            })))]
        )
        history = [
            {
                "role": "system",
                "content": (
                    "RECENT CHAT TURNS (same chat and project):\n"
                    "User: Create resource group testing_eq in eastus.\n"
                    "Assistant: The Azure target is testing_eq in eastus."
                ),
            },
            {"role": "user", "content": "show it"},
        ]

        planned = plan_action("show it", history, "Azure connected")

        self.assertEqual(planned["kind"], "action")
        prompt = chat.call_args.args[0][1]["content"]
        self.assertIn("testing_eq", prompt)
        self.assertIn("eastus", prompt)


if __name__ == "__main__":
    unittest.main()
