"""Orchestrator live-context, single-skill, and plan/agent entrypoints."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from app.chat.orchestrator import (
    AgentRun,
    ChatTurn,
    PlanStep,
    _ensure_planned_context,
    _gather_live_context,
    _provider_block,
    _run_single_skill,
    _synthesise,
    execute_plan_stream,
    run_chat,
    run_chat_stream,
)
from app.skills.base import SkillResult


@pytest.mark.unit
def test_gather_live_context_when_providers_disconnected():
    with patch("app.chat.orchestrator._gather_cost_context", return_value=None):
        with patch("app.chat.orchestrator._gather_metrics_context", return_value=(None, [])):
            with patch("app.chat.orchestrator._gather_logs_context", return_value=(None, [])):
                with patch("app.chat.orchestrator._gather_code_context", return_value=None):
                    with patch("app.chat.orchestrator._provider_block", return_value=None):
                        with patch("app.chat.orchestrator.azure_infra.is_connected", return_value=False):
                            with patch("app.chat.orchestrator.github_infra.is_connected", return_value=False):
                                text, charts = _gather_live_context(
                                    "hello", "p1", force=True, force_security=False
                                )
    assert text is None
    assert charts == []


@pytest.mark.unit
def test_gather_live_context_diagnostic_adds_default_scopes():
    with patch("app.chat.orchestrator._gather_cost_context", return_value=None):
        with patch("app.chat.orchestrator._gather_metrics_context", return_value=(None, [])):
            with patch("app.chat.orchestrator._gather_logs_context", return_value=(None, [])):
                with patch(
                    "app.chat.orchestrator._gather_code_context",
                    return_value="CODE BLOCK",
                ):
                    with patch("app.chat.orchestrator._provider_block", return_value="AZURE LIVE"):
                        with patch("app.chat.orchestrator.azure_infra.is_connected", return_value=True):
                            with patch("app.chat.orchestrator.github_infra.is_connected", return_value=True):
                                text, _charts = _gather_live_context(
                                    "review azure posture vs github", "p1"
                                )
    assert text is not None
    assert "DEFAULT AZURE SCOPE" in text
    assert "DEFAULT GITHUB SCOPE" in text


@pytest.mark.unit
def test_provider_block_not_connected_or_not_triggered():
    spec = {
        "module": MagicMock(is_connected=lambda _pid: False),
        "triggers": ["azure"],
        "label": "AZURE",
        "name": "azure",
        "source": "ARM",
        "conn_err": Exception,
        "api_err": Exception,
        "advice": "check creds",
    }
    assert _provider_block(spec, False, "hello", "p1") is None
    spec["module"].is_connected = lambda _pid: True
    spec["module"].build_environment_report = lambda _pid: {"text": "LIVE"}
    assert "LIVE" in _provider_block(spec, True, "hello", "p1")
    spec["module"].build_environment_report = MagicMock(side_effect=RuntimeError("boom"))
    spec["api_err"] = RuntimeError
    spec["conn_err"] = ValueError
    assert "FETCH FAILED" in _provider_block(spec, True, "hello", "p1")


@pytest.mark.unit
def test_run_single_skill_missing_and_success():
    missing = _run_single_skill("nope", "task", "policy", None)
    assert "not found" in missing.reply
    skill = MagicMock()
    skill.run.return_value = SkillResult(skill="report_writer", content="ok")
    with patch("app.chat.orchestrator.registry.get", return_value=skill):
        turn = _run_single_skill("report_writer", "task", "policy", "live")
    assert turn.reply == "ok"
    assert turn.skills_used == ["report_writer"]


@pytest.mark.unit
def test_synthesise_single_and_multi():
    one = [AgentRun(skill="a", objective="o", output="only")]
    assert _synthesise("t", one) == "only"
    completion = MagicMock()
    completion.choices = [MagicMock(message=MagicMock(content="combined"))]
    with patch("app.chat.orchestrator.azure_client.chat", return_value=completion):
        text = _synthesise(
            "t",
            [
                AgentRun(skill="a", objective="o", output="one"),
                AgentRun(skill="b", objective="o", output="two"),
            ],
        )
    assert text == "combined"


@pytest.mark.unit
def test_run_chat_auto_routes_to_multi_agent():
    expected = ChatTurn(mode="agent", reply="done")
    with patch("app.chat.orchestrator._gather_project_topology", return_value="topo"):
        with patch("app.chat.orchestrator._gather_live_context", return_value=("live", [])):
            with patch("app.chat.orchestrator.provider_status_text", return_value="status"):
                with patch("app.chat.orchestrator._run_multi_agent", return_value=expected):
                    turn = run_chat(
                        [{"role": "user", "content": "audit pipelines"}],
                        "p1",
                    )
    assert turn.reply == "done"


@pytest.mark.unit
def test_run_chat_plan_mode():
    planned = ChatTurn(mode="plan", reply="plan")
    with patch("app.chat.orchestrator._gather_project_topology", return_value="topo"):
        with patch("app.chat.orchestrator._gather_live_context", return_value=("live", [])):
            with patch("app.chat.orchestrator.provider_status_text", return_value="status"):
                with patch("app.chat.orchestrator._run_plan_mode", return_value=planned):
                    turn = run_chat(
                        [{"role": "user", "content": "plan this"}],
                        "p1",
                        mode="plan",
                    )
    assert turn.mode == "plan"


@pytest.mark.unit
def test_ensure_planned_context_fetches_missing_metrics():
    steps = [PlanStep(skill="metrics_analyzer", objective="cpu")]
    with patch(
        "app.chat.orchestrator._gather_metrics_context",
        return_value=("METRICS", [{"id": "c1"}]),
    ):
        text, charts = _ensure_planned_context("cpu", "p1", steps, None, [])
    assert "METRICS" in (text or "")
    assert charts


@pytest.mark.unit
def test_run_chat_stream_yields_final():
    def fake_stream(*_a, **_k):
        yield {"type": "delta", "text": "hi"}
        yield {"type": "final", "mode": "agent", "reply": "hi"}

    with patch("app.chat.orchestrator._gather_project_topology", return_value=""):
        with patch("app.chat.orchestrator._gather_live_context", return_value=(None, [])):
            with patch("app.chat.orchestrator.provider_status_text", return_value=""):
                with patch(
                    "app.chat.orchestrator._build_plan",
                    return_value=("summary", [PlanStep(skill="report_writer", objective="write")], []),
                ):
                    with patch("app.chat.orchestrator._ensure_planned_context", return_value=(None, [])):
                        with patch("app.chat.orchestrator._stream_steps", side_effect=fake_stream):
                            events = list(
                                run_chat_stream(
                                    [{"role": "user", "content": "hi"}],
                                    "p1",
                                )
                            )
    assert events[-1]["type"] == "final"


@pytest.mark.unit
def test_execute_plan_stream_with_no_azure_steps():
    def fake_stream(*_a, **_k):
        yield {"type": "final", "mode": "agent", "reply": "ran"}

    with patch("app.chat.orchestrator._gather_project_topology", return_value=""):
        with patch("app.chat.orchestrator._gather_live_context", return_value=(None, [])):
            with patch("app.chat.orchestrator.provider_status_text", return_value=""):
                with patch(
                    "app.chat.orchestrator._ensure_planned_context",
                    return_value=(None, []),
                ):
                    with patch("app.chat.orchestrator._stream_steps", side_effect=fake_stream):
                        events = list(
                            execute_plan_stream(
                                [{"role": "user", "content": "go"}],
                                "p1",
                                [PlanStep(skill="report_writer", objective="write")],
                            )
                        )
    assert events[-1]["reply"] == "ran"
