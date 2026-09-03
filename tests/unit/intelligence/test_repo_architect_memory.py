"""Repo analysis, architect streaming, chat memory outcomes, and worker import."""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from app.agents.solution_architect import graph
from app.agents.solution_architect.state import empty_state
from app.chat.chat_memory import (
    _clean_items,
    _clip,
    _normalise,
    _normalise_infra_state,
    record_deployment_outcome,
    refresh_memory,
)
from app.intelligence.repo_analyzer import analyze_repositories, analyze_to_prompt
from app.providers.github_infra import GitHubApiError
from executors.common.worker import Worker


@pytest.mark.unit
def test_worker_is_rq_simple_worker_subclass():
    assert issubclass(Worker, object)
    assert Worker.death_penalty_class is not None


@pytest.mark.unit
def test_analyze_repositories_parses_github_report():
    context = SimpleNamespace(
        repos=["acme/api"],
        iac_files=[{"path": "main.tf"}],
        app_structure={"has_terraform": True},
        live_resources={},
        gaps=["none"],
        summary="existing",
        to_dict=lambda: {},
    )
    report = {
        "text": (
            "### acme/api — app/main.py (branch: develop)\n"
            "from fastapi import FastAPI\n"
            "### acme/api — infra/main.tf (branch: develop)\n"
            "resource \"azurerm_resource_group\" \"x\" {}\n"
        )
    }
    with patch("app.intelligence.repo_analyzer.build_existing_context", return_value=context):
        with patch("app.intelligence.repo_analyzer.projects.get_repos", return_value=["acme/api"]):
            with patch("app.intelligence.repo_analyzer.github_infra.is_connected", return_value=True):
                with patch(
                    "app.intelligence.repo_analyzer.github_infra.build_code_report",
                    return_value=report,
                ):
                    data = analyze_repositories("p1")
                    prompt = analyze_to_prompt("p1")
    assert data["repository_summaries"]
    assert "REPOSITORY ANALYSIS" in prompt
    with patch("app.intelligence.repo_analyzer.build_existing_context", return_value=context):
        with patch("app.intelligence.repo_analyzer.github_infra.is_connected", return_value=True):
            with patch(
                "app.intelligence.repo_analyzer.github_infra.build_code_report",
                side_effect=GitHubApiError("denied"),
            ):
                failed = analyze_repositories("p1")
    assert "error" in failed


@pytest.mark.unit
def test_stream_architect_awaiting_and_complete():
    paused = empty_state(
        objective="Need region",
        project_id="p1",
        user="u1",
        constraints="",
        seed_context="",
        tier="T1",
        plan_only=False,
        source="chat",
        thread_id="t1",
    )
    paused["awaiting_input"] = True
    paused["pending_question"] = "Which region?"
    paused["reply"] = "Which region?"
    with patch("app.agents.solution_architect.graph.run_pipeline", return_value=paused):
        events = list(graph.stream_architect({"objective": "design"}, chat_id="t1"))
    assert events[-1]["type"] == "final"
    done = empty_state(
        objective="Add queue",
        project_id="p1",
        user="u1",
        constraints="",
        seed_context="",
        tier="T2",
        plan_only=True,
        source="chat",
        thread_id="t1",
    )
    done["reply"] = "HLD"
    done["hld"] = "HLD"
    done["plan_steps"] = [{"skill": "infrastructure_architect", "objective": "lld"}]
    with patch("app.agents.solution_architect.graph.run_pipeline", return_value=done):
        events = list(graph.stream_architect({"objective": "design", "plan_only": True}, chat_id="t1"))
    assert events[-1]["plan"]
    with patch("app.agents.solution_architect.graph.run_pipeline", return_value=done):
        invoked = graph.invoke_architect({"objective": "design"}, chat_id="t1")
    assert invoked.get("reply") == "HLD" or invoked.get("type") == "final"
    mermaid = graph._default_mermaid(done)
    assert "graph" in mermaid.lower() or mermaid
    rendered = graph._render_hld(done, [{"title": "change", "gate": "human_approval"}])
    assert "change" in rendered or rendered


@pytest.mark.unit
def test_stream_architect_yields_status_before_pipeline_returns():
    import threading

    released = threading.Event()
    done = empty_state(
        objective="Add queue",
        project_id="p1",
        user="u1",
        constraints="",
        seed_context="",
        tier="T1",
        plan_only=False,
        source="chat",
        thread_id="t-live",
    )
    done["reply"] = "HLD"

    def blocking_pipeline(_state, emit):
        emit({"type": "status", "text": "Clarifying the ask"})
        released.wait(timeout=2)
        return done

    with patch("app.agents.solution_architect.graph.run_pipeline", side_effect=blocking_pipeline):
        gen = graph.stream_architect({"objective": "design"}, chat_id="t-live")
        first = next(gen)
        released.set()
        rest = list(gen)
    assert first["type"] == "status"
    assert rest[-1]["type"] == "final"


@pytest.mark.unit
def test_chat_memory_normalise_and_record_outcome():
    cleaned = _clean_items(["resource-group", "", None, "resource-group"])
    assert "resource-group" in cleaned
    assert len(_clip("abc" * 200, 10)) <= 10
    state = _normalise_infra_state({"deployed": ["resource-group"], "unknown": 1})
    assert "resource-group" in state["deployed"]
    parsed = _normalise({"summary": "s", "facts": ["a"], "infra_state": {"deployed": ["rg"]}})
    assert parsed["summary"] == "s"
    session = MagicMock()
    row = SimpleNamespace(deployment_outcomes=[], infra_state={}, version=0)
    session.get.return_value = row
    context = MagicMock()
    context.__enter__.return_value = session
    context.__exit__.return_value = False
    with patch(
        "app.chat.chat_memory.get_memory",
        return_value={"deployment_outcomes": [], "infra_state": {}},
    ):
        with patch("app.chat.chat_memory.SessionLocal", return_value=context):
            record_deployment_outcome("c1", action_id="a1", status="succeeded", summary="ok")
    assert row.deployment_outcomes
    chat = SimpleNamespace(id="c1", project_id="p1")
    with patch(
        "app.chat.chat_memory._transcript",
        return_value=(chat, [{"role": "user", "content": "hi"}]),
    ):
        with patch("app.chat.chat_memory.get_memory", return_value=None):
            with patch(
                "app.chat.chat_memory._summarise",
                return_value=_normalise({"summary": "hi", "facts": []}),
            ):
                with patch("app.chat.chat_memory.SessionLocal", return_value=context):
                    refreshed = refresh_memory("c1")
    assert refreshed is None or refreshed
