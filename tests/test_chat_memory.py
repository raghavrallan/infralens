import json
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from app.chat_memory import (
    _fallback,
    redact,
    refresh_memory,
    render_recent_context,
    render_model_context,
)


class ChatMemoryTests(unittest.TestCase):
    def test_context_contains_memory_and_current_turn_only(self):
        memory = {
            "summary": "The user is working with resource group testing in eastus.",
            "facts": ["Azure subscription is configured"],
            "references": ["resource-group/testing", "metric=cpu"],
            "unresolved": ["Confirm the deployment action"],
        }
        context = render_model_context(memory, "use the same region")
        self.assertEqual([item["role"] for item in context], ["system", "user"])
        self.assertIn("resource-group/testing", context[0]["content"])
        self.assertEqual(context[1]["content"], "use the same region")
        self.assertNotIn("an old transcript turn", json.dumps(context))

    def test_redaction_removes_secret_values_but_preserves_resource_ids(self):
        value = {
            "client_secret": "super-secret-value",
            "text": "Bearer abcdefghijklmnopqrstuvwxyz1234567890",
            "args": ["--client-secret", "short-secret", "--name", "testing"],
            "resource": "resource-group/testing",
        }
        redacted = redact(value)
        self.assertEqual(redacted["client_secret"], "[REDACTED]")
        self.assertNotIn("super-secret-value", json.dumps(redacted))
        self.assertNotIn("abcdefghijklmnopqrstuvwxyz1234567890", redacted["text"])
        self.assertEqual(redacted["args"][1], "[REDACTED]")
        self.assertEqual(redacted["args"][3], "testing")
        self.assertEqual(redacted["resource"], "resource-group/testing")

    def test_recent_context_preserves_exact_details_for_follow_ups(self):
        transcript = [
            {
                "role": "user",
                "content": "Show CPU and memory for my container apps over the last 24 hours.",
            },
            {
                "role": "assistant",
                "content": "The metric report covers eq-cap-container-dev-eastus-001 for the last 24 hours.",
            },
            {"role": "user", "content": "Give me the metric for this particular hour."},
        ]

        context = render_recent_context(transcript, transcript[-1]["content"])

        self.assertIn("eq-cap-container-dev-eastus-001", context)
        self.assertIn("CPU and memory", context)
        self.assertNotIn("this particular hour", context)

    def test_fallback_is_bounded_and_contains_latest_turn(self):
        messages = [
            {"role": "user", "content": "old transcript turn"},
            {"role": "user", "content": "Create resource group testing in eastus"},
            {"role": "assistant", "content": "Awaiting confirmation for testing."},
        ]
        fallback = _fallback(messages)
        self.assertIn("testing", fallback["summary"])
        self.assertLessEqual(len(fallback["summary"]), 2400)

    @patch("app.chat_memory.SessionLocal")
    @patch("app.chat_memory._summarise", side_effect=RuntimeError("model unavailable"))
    @patch("app.chat_memory.get_memory", return_value=None)
    @patch("app.chat_memory._transcript")
    def test_summary_failure_uses_fallback_without_failing_refresh(
        self, transcript, _memory, _summarise, session_local
    ):
        chat = SimpleNamespace(project_id="project-1")
        messages = [{"role": "user", "content": "Create testing in eastus"}]
        transcript.return_value = (chat, messages)
        session = MagicMock()
        session.get.return_value = None
        context = MagicMock()
        context.__enter__.return_value = session
        context.__exit__.return_value = False
        session_local.return_value = context

        result = refresh_memory("chat-1")

        self.assertIsNotNone(result)
        self.assertIn("testing", result["summary"])
        self.assertEqual(result["project_id"], "project-1")
        session.commit.assert_called()


if __name__ == "__main__":
    unittest.main()
