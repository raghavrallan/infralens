"""Planner, multi-agent, gather-context, and stream-step paths with mocked LLM/providers."""
from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from app.chat.orchestrator import (
    AgentRun,
    PlanStep,
    _build_plan,
    _gather_code_context,
    _gather_cost_context,
    _gather_logs_context,
    _gather_metrics_context,
    _gather_security_context,
    _run_multi_agent,
    _run_plan_mode,
    _stream_and_collect,
    _stream_steps,
)
from app.providers.github_infra import GitHubApiError
from app.skills.base import SkillResult


def _llm(payload: dict | str) -> MagicMock:
    content = payload if isinstance(payload, str) else json.dumps(payload)
    return MagicMock(choices=[MagicMock(message=MagicMock(content=content))])


@pytest.mark.unit
def test_build_plan_returns_registered_skill_steps():
    with patch(
        "app.chat.orchestrator.azure_client.chat",
        return_value=_llm(
            {
                "summary": "review posture",
                "needs_clarification": False,
                "steps": [
                    {"skill": "cloud_posture", "objective": "review azure"},
                    {"skill": "not_a_skill", "objective": "skip"},
                ],
            }
        ),
    ):
        summary, steps, questions = _build_plan(
            [{"role": "user", "content": "review azure security posture"}]
        )
    assert summary == "review posture"
    assert questions == []
    assert any(step.skill == "cloud_posture" for step in steps)


@pytest.mark.unit
def test_build_plan_clarification_when_no_live_data():
    with patch(
        "app.chat.orchestrator.azure_client.chat",
        return_value=_llm(
            {
                "summary": "need more",
                "needs_clarification": True,
                "clarification_questions": ["Which team owns this service?"],
                "steps": [],
            }
        ),
    ):
        _summary, steps, questions = _build_plan(
            [{"role": "user", "content": "please help with something unique xyz"}]
        )
    assert steps == []
    assert questions


@pytest.mark.unit
def test_run_multi_agent_clarifies_and_runs_skills():
    with patch(
        "app.chat.orchestrator._build_plan",
        return_value=("need info", [], ["Which repo?"]),
    ):
        turn = _run_multi_agent(
            [{"role": "user", "content": "help"}],
            "policy",
            None,
            "p1",
        )
    assert turn.needs_clarification is True
    skill = MagicMock()
    skill.run.return_value = SkillResult(skill="cloud_posture", content="findings")
    with patch(
        "app.chat.orchestrator._build_plan",
        return_value=(
            "review",
            [PlanStep(skill="cloud_posture", objective="review")],
            [],
        ),
    ):
        with patch("app.chat.orchestrator._ensure_planned_context", return_value=("live", [])):
            with patch("app.chat.orchestrator.registry.get", return_value=skill):
                turn = _run_multi_agent(
                    [{"role": "user", "content": "review azure"}],
                    "policy",
                    "live",
                    "p1",
                )
    assert "findings" in turn.reply
    assert turn.skills_used == ["cloud_posture"]


@pytest.mark.unit
def test_run_plan_mode_formats_detailed_plan():
    parsed = {
        "understanding": "User wants a review",
        "findings": "NSG is open",
        "issues": ["public nsg"],
        "resolution": "restrict",
        "needs_clarification": False,
        "steps": [{"skill": "cloud_posture", "objective": "review"}],
    }
    with patch(
        "app.chat.orchestrator._build_detailed_plan",
        return_value=(parsed, [PlanStep(skill="cloud_posture", objective="review")]),
    ):
        turn = _run_plan_mode([{"role": "user", "content": "review azure"}], "LIVE DATA")
    assert turn.mode == "plan"
    assert turn.plan
    assert "review" in turn.reply.lower() or "NSG" in turn.reply or turn.reply


@pytest.mark.unit
def test_gather_code_cost_metrics_logs_and_security():
    with patch("app.chat.orchestrator.github_infra.is_connected", return_value=False):
        assert _gather_code_context("show terraform", "p1") is None
    with patch("app.chat.orchestrator.github_infra.is_connected", return_value=True):
        with patch(
            "app.chat.orchestrator.github_infra.build_code_report",
            return_value={"text": "LIVE GITHUB CODE"},
        ):
            assert "LIVE GITHUB CODE" in (_gather_code_context("show terraform", "p1") or "")
        with patch(
            "app.chat.orchestrator.github_infra.build_code_report",
            side_effect=GitHubApiError("nope"),
        ):
            failed = _gather_code_context("show terraform", "p1")
            assert failed and "FETCH FAILED" in failed
    with patch("app.chat.orchestrator.azure_infra.is_connected", return_value=False):
        assert _gather_cost_context("billing last month", "p1") is None
        assert _gather_metrics_context("cpu last 24 hours", "p1") == (None, [])
        assert _gather_logs_context("show 500 errors", "p1") == (None, [])
    with patch("app.chat.orchestrator.azure_infra.is_connected", return_value=True):
        with patch(
            "app.chat.orchestrator.azure_infra.build_cost_report",
            return_value={"text": "$12"},
        ):
            text = _gather_cost_context("what did we spend last month", "p1")
            assert text and "LIVE AZURE BILLING" in text
        with patch(
            "app.chat.orchestrator.azure_infra.build_metrics_report",
            return_value={"text": "cpu 2%", "charts": [{"id": "c"}]},
        ):
            text, charts = _gather_metrics_context("cpu last 24 hours", "p1")
            assert text and charts
        with patch(
            "app.chat.orchestrator.azure_infra.build_status_report",
            return_value={"text": "500=2", "charts": []},
        ):
            with patch(
                "app.chat.orchestrator.azure_infra.build_logs_report",
                return_value={"text": "boom"},
            ):
                text, _charts = _gather_logs_context("show me the errors and logs", "p1")
                assert text and "TELEMETRY" in text
    with patch("app.chat.orchestrator._provider_block", return_value="AZURE LIVE"):
        with patch("app.chat.orchestrator.github_infra.is_connected", return_value=False):
            sec = _gather_security_context("find vulnerabilities", "p1")
            assert sec and "AZURE LIVE" in sec


@pytest.mark.unit
def test_stream_steps_direct_and_single_skill():
    with patch(
        "app.chat.orchestrator.azure_client.stream_chat",
        return_value=iter(["hello", " world"]),
    ):
        events = list(
            _stream_steps(
                "hi",
                [{"role": "user", "content": "hi"}],
                [],
                "policy",
                None,
            )
        )
    assert events[-1]["type"] == "final"
    assert "hello" in events[-1]["reply"]
    skill = MagicMock()
    skill.is_agentic = False
    skill.name = "report_writer"
    skill.run.return_value = SkillResult(skill="report_writer", content="done")

    def deltas(_sk, _args):
        yield "done"

    with patch("app.chat.orchestrator.registry.get", return_value=skill):
        with patch("app.chat.orchestrator._skill_deltas", side_effect=deltas):
            events = list(
                _stream_steps(
                    "write",
                    [{"role": "user", "content": "write"}],
                    [PlanStep(skill="report_writer", objective="write")],
                    "policy",
                    "live",
                )
            )
    assert events[-1]["skills_used"] == ["report_writer"]


@pytest.mark.unit
def test_stream_and_collect_yields_deltas():
    collected = []
    gen = _stream_and_collect(iter(["a", "b"]))
    try:
        while True:
            collected.append(next(gen))
    except StopIteration as stop:
        content = stop.value
    assert content == "ab"
    assert collected[0]["type"] == "delta"
