"""Solution Architect graph nodes with mocked LLM and tools."""
from __future__ import annotations

from unittest.mock import patch

import pytest

import app.skills  # noqa: F401 — break circular import before architect graph
from app.agents.solution_architect import graph
from app.agents.solution_architect.state import empty_state


@pytest.mark.unit
def test_json_chat_requires_azure_config():
    with patch("app.agents.solution_architect.graph.app_config.get_azure_config") as cfg:
        cfg.return_value.configured = False
        with pytest.raises(RuntimeError, match="not configured"):
            graph._json_chat("sys", "user", "n")


@pytest.mark.unit
def test_json_chat_parses_and_raises_on_errors():
    class Cfg:
        configured = True

    with patch("app.agents.solution_architect.graph.app_config.get_azure_config", return_value=Cfg()):
        with patch(
            "app.agents.solution_architect.graph.azure_client.chat",
            return_value=type(
                "C",
                (),
                {"choices": [type("Ch", (), {"message": type("M", (), {"content": '{"ok": true}'})()})()]},
            )(),
        ):
            assert graph._json_chat("s", "u", "n") == {"ok": True}
        with patch(
            "app.agents.solution_architect.graph.azure_client.chat",
            side_effect=RuntimeError("boom"),
        ):
            with pytest.raises(RuntimeError, match="Azure OpenAI request failed"):
                graph._json_chat("s", "u", "n")


@pytest.mark.unit
def test_run_pipeline_greenfield_without_pause():
    events: list[dict] = []
    state = empty_state(
        objective="Add a queue beside the API",
        project_id="p1",
        user="u1",
        constraints="",
        seed_context="",
        tier="T1",
        plan_only=False,
        source="chat",
        thread_id="thread-1",
    )
    parsed = {
        "objective": "Add a queue beside the API",
        "constraints": "",
        "tier": "T1",
        "assumptions": ["managed service"],
        "needs_question": False,
        "question": "",
        "candidates": [],
        "mermaid": "graph TD; A-->B;",
        "hld_outline": "HLD",
        "notes": "ok",
        "revise": False,
        "decisions": [],
        "plan_steps": [{"skill": "infrastructure_architect", "objective": "LLD"}],
        "hld": "final hld",
    }
    patches = {
        "app.agents.solution_architect.graph.governance.load_paused": None,
        "app.agents.solution_architect.graph._json_chat": parsed,
        "app.agents.solution_architect.graph.tools.get_cloud_inventory": "empty",
        "app.agents.solution_architect.graph.tools.get_code_artifacts": "",
        "app.agents.solution_architect.graph.tools.inventory_is_empty": True,
        "app.agents.solution_architect.graph.tools.search_precedent": "",
        "app.agents.solution_architect.graph.tools.preview_gate": {"gate": "auto", "label": "auto"},
        "app.agents.solution_architect.graph.governance.upsert_run": "run-1",
        "app.agents.solution_architect.graph.governance.persist_decisions": [
            {"title": "queue", "change": "add queue"}
        ],
        "app.agents.solution_architect.graph.governance.high_gate_unjustified": False,
    }
    stacked = [patch(name, return_value=value) for name, value in patches.items()]
    with patch("app.platform.engineering.generate.apply_architect_result", return_value={"ok": True}):
        with stacked[0], stacked[1], stacked[2], stacked[3], stacked[4], stacked[5], stacked[6], stacked[7], stacked[8], stacked[9]:
            result = graph.run_pipeline(state, emit=events.append)
    assert result.get("reply")
    assert result.get("architecture")
    assert any(event.get("type") == "status" for event in events)


@pytest.mark.unit
def test_clarify_pauses_for_t2_question():
    state = empty_state(
        objective="PCI redesign",
        project_id="p1",
        user="u1",
        tier="T2",
        thread_id="t2",
    )
    with patch(
        "app.agents.solution_architect.graph._json_chat",
        return_value={
            "objective": "PCI redesign",
            "tier": "T2",
            "needs_question": True,
            "question": "What is the cardholder data flow?",
            "assumptions": [],
        },
    ):
        with patch("app.agents.solution_architect.graph.governance.upsert_run", return_value="run-2"):
            with patch("app.agents.solution_architect.graph.governance.load_paused", return_value=None):
                paused = graph.run_pipeline(state)
    assert paused.get("awaiting_input") is True
    assert "cardholder" in (paused.get("pending_question") or "")


@pytest.mark.unit
def test_invoke_architect_and_initial_state():
    args = {
        "objective": "small api change",
        "project_id": "p1",
        "plan_only": True,
    }
    initial = graph._initial_state(args, "chat-1")
    assert initial["thread_id"] == "chat-1"
    assert initial["plan_only"] is True
    with patch("app.agents.solution_architect.graph.stream_architect") as stream:
        stream.return_value = iter([{"type": "final", "reply": "done"}])
        result = graph.invoke_architect(args, chat_id="chat-1")
    assert result["reply"] == "done"


@pytest.mark.unit
def test_default_mermaid_and_render_hld():
    state = empty_state(objective="queue", tier="T1")
    diagram = graph._default_mermaid(state)
    assert "graph" in diagram.lower() or "flowchart" in diagram.lower() or diagram
    rendered = graph._render_hld(state, [{"title": "queue", "change": "add it"}])
    assert rendered
