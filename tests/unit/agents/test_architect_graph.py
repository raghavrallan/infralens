"""Solution Architect graph nodes with mocked LLM and tools."""
from __future__ import annotations

from unittest.mock import patch

import pytest

import app.skills  # noqa: F401 — break circular import before architect graph
from app.agents.solution_architect import graph
from app.agents.solution_architect.state import empty_state


@pytest.mark.unit
def test_json_chat_returns_empty_when_azure_unconfigured():
    with patch("app.agents.solution_architect.graph.app_config.get_azure_config") as cfg:
        cfg.return_value.configured = False
        assert graph._json_chat("sys", "user", "n") == {}


@pytest.mark.unit
def test_json_chat_parses_and_swallows_errors():
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
            assert graph._json_chat("s", "u", "n") == {}


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
    with patch("app.agents.solution_architect.graph.governance.load_paused", return_value=None):
        with patch("app.agents.solution_architect.graph._json_chat", return_value=parsed):
            with patch("app.agents.solution_architect.graph.tools.get_cloud_inventory", return_value="empty"):
                with patch("app.agents.solution_architect.graph.tools.inventory_is_empty", return_value=True):
                    with patch("app.agents.solution_architect.graph.tools.search_precedent", return_value=""):
                        with patch(
                            "app.agents.solution_architect.graph.tools.preview_gate",
                            return_value={"gate": "auto", "label": "auto"},
                        ):
                            with patch(
                                "app.agents.solution_architect.graph.governance.upsert_run",
                                return_value="run-1",
                            ):
                                with patch(
                                    "app.agents.solution_architect.graph.governance.persist_decisions",
                                    return_value=[{"title": "queue", "change": "add queue"}],
                                ):
                                    with patch(
                                        "app.agents.solution_architect.graph.governance.high_gate_unjustified",
                                        return_value=False,
                                    ):
                                        result = graph.run_pipeline(state, emit=events.append)
    assert result.get("reply")
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
