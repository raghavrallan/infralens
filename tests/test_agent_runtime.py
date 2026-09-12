"""Unit tests for agent runtime flags, policies, and webhook signing."""
from __future__ import annotations

import os

import pytest


def test_feature_flags_default_off(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ARCHITECT_LANGGRAPH", raising=False)
    monkeypatch.delenv("N8N_WEBHOOKS_ENABLED", raising=False)
    monkeypatch.delenv("DEBUG_REACT_ENABLED", raising=False)
    monkeypatch.delenv("CHAT_LANGGRAPH", raising=False)
    from app.agents.runtime import flags

    flags.clear_flag_cache()
    got = flags.get_feature_flags()
    assert got["architect_langgraph"] is False
    assert got["n8n_webhooks"] is False
    assert got["debug_react"] is False
    assert got["chat_langgraph"] is False


def test_feature_flags_truthy(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ARCHITECT_LANGGRAPH", "true")
    monkeypatch.setenv("N8N_WEBHOOKS_ENABLED", "1")
    from app.agents.runtime import flags

    flags.clear_flag_cache()
    assert flags.feature_enabled("architect_langgraph") is True
    assert flags.feature_enabled("n8n_webhooks") is True
    flags.clear_flag_cache()


def test_agent_loop_policy_budgets() -> None:
    from app.agents.runtime.policies import default_architect_policy, default_debug_policy

    arch = default_architect_policy()
    assert arch.can_revise(0) is True
    assert arch.can_revise(2) is False
    debug = default_debug_policy()
    assert debug.can_retry(2) is True
    assert debug.can_retry(3) is False
    assert "execute" in debug.require_gate_before


def test_webhook_sign_and_verify() -> None:
    from app.integrations import webhooks

    body = b'{"event":"approval.created"}'
    secret = "test-secret"
    sig = webhooks.sign_body(body, secret)
    assert sig.startswith("sha256=")
    assert webhooks.verify_signature(body, sig, secret) is True
    assert webhooks.verify_signature(body, "sha256=deadbeef", secret) is False


def test_n8n_envelope_shape() -> None:
    from app.integrations import n8n_schemas

    payload = n8n_schemas.approval_created(
        approval_id="a1",
        finding_id="f1",
        project_id="p1",
        gate="human_approval",
        severity="high",
        title="Disable public blob",
    )
    assert payload["event"] == "approval.created"
    assert payload["source"] == "infralens"
    assert payload["data"]["approval_id"] == "a1"
    assert "deep_link" in payload["data"]


def test_emit_event_noop_when_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("N8N_WEBHOOKS_ENABLED", "false")
    monkeypatch.delenv("N8N_WEBHOOK_URL", raising=False)
    from app.agents.runtime import flags
    from app.integrations import n8n_schemas, webhooks

    flags.clear_flag_cache()
    assert webhooks.emit_event(n8n_schemas.envelope("approval.decided", data={})) is False


def test_architect_needs_revision_state_default() -> None:
    from app.agents.solution_architect.state import empty_state

    state = empty_state(objective="design a vpc")
    assert state.get("needs_revision") is False


def test_langgraph_builder_compiles() -> None:
    from langgraph.checkpoint.memory import MemorySaver

    from app.agents.solution_architect.lg_graph import build_architect_graph

    graph = build_architect_graph(checkpointer=MemorySaver())
    assert graph is not None


def test_debug_react_facade_propose_only(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DEBUG_REACT_ENABLED", "true")
    from app.agents.runtime import flags

    flags.clear_flag_cache()

    from app.agents import debug_graph

    monkeypatch.setattr(
        debug_graph.legacy,
        "propose_fix",
        lambda action_id, project_context="": {
            "action_id": action_id,
            "retry_safe": False,
            "notes": "unsafe",
            "root_cause": "x",
            "fix_summary": "y",
        },
    )
    result = debug_graph.run_debug_react("act-1", create_retry=True)
    assert result["status"] == "unsafe"
    flags.clear_flag_cache()
