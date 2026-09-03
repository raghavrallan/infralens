"""Orchestrator streaming, agentic, multi-step, and remaining planner branches."""
from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from app.chat.orchestrator import (
    ChatTurn,
    PlanStep,
    _build_plan,
    _gather_security_context,
    _parse_metric_intent,
    _skill_args,
    _skill_deltas,
    _stream_agentic,
    _stream_steps,
    execute_plan_stream,
    run_chat,
    run_chat_stream,
)
from app.providers.github_infra import GitHubApiError, GitHubConnectionError
from app.skills.base import SkillResult


def _llm(payload: dict | str) -> MagicMock:
    content = payload if isinstance(payload, str) else json.dumps(payload)
    return MagicMock(choices=[MagicMock(message=MagicMock(content=content))])


def _plain_skill(name: str = "report_writer", content: str = "done") -> MagicMock:
    skill = MagicMock()
    skill.is_agentic = False
    skill.json_output = True
    skill.name = name
    skill.temperature = 0.2
    skill.run.return_value = SkillResult(skill=name, content=content)
    skill.build_messages.return_value = [{"role": "user", "content": "x"}]
    return skill


@pytest.mark.unit
def test_skill_deltas_json_agentic_and_stream():
    json_skill = _plain_skill()
    assert list(_skill_deltas(json_skill, {"task": "x"})) == ["done"]

    agentic = MagicMock()
    agentic.is_agentic = True
    agentic.name = "solution_architect"
    agentic.stream_events.return_value = [
        {"type": "delta", "text": "hello"},
        {"type": "status", "text": "working"},
        {"type": "final", "reply": "hello"},
    ]
    assert list(_skill_deltas(agentic, {"chat_id": "c1"})) == ["hello"]

    stream_skill = _plain_skill()
    stream_skill.json_output = False
    with patch(
        "app.chat.orchestrator.azure_client.stream_chat",
        return_value=iter(["a", "b"]),
    ):
        assert "".join(_skill_deltas(stream_skill, {})) == "ab"


@pytest.mark.unit
def test_stream_agentic_collects_final_and_tier():
    skill = MagicMock()
    skill.name = "solution_architect"
    skill.stream_events.return_value = [
        {"type": "delta", "text": "part"},
        {"type": "final", "reply": "done", "plan": [{"skill": "report_writer", "objective": "x"}], "tier": "T1", "architect_mode": "greenfield", "skills_used": ["solution_architect"]},
    ]
    events = list(_stream_agentic(skill, {"objective": "design"}, chat_id="c1", plan_only=True))
    assert events[-1]["type"] == "final"
    assert events[-1]["tier"] == "T1"
    assert events[-1]["reply"] == "done"


@pytest.mark.unit
def test_stream_steps_multi_skill_and_agentic_single():
    writer = _plain_skill("report_writer", "alpha")
    posture = _plain_skill("cloud_posture", "beta")
    with patch(
        "app.chat.orchestrator.registry.get",
        side_effect=lambda name: {"report_writer": writer, "cloud_posture": posture}.get(name),
    ):
        with patch(
            "app.chat.orchestrator.azure_client.stream_chat",
            return_value=iter(["combined"]),
        ):
            events = list(
                _stream_steps(
                    "review",
                    [{"role": "user", "content": "review"}],
                    [
                        PlanStep(skill="report_writer", objective="write"),
                        PlanStep(skill="cloud_posture", objective="review"),
                        PlanStep(skill="missing", objective="skip"),
                    ],
                    "policy",
                    "live",
                    charts=[{"id": "c1"}],
                    chat_id="c1",
                    project_id="p1",
                )
            )
    assert events[-1]["type"] == "final"
    assert "report_writer" in events[-1]["skills_used"]
    assert events[-1]["charts"] == [{"id": "c1"}]

    agentic = MagicMock()
    agentic.is_agentic = True
    agentic.name = "solution_architect"
    agentic.stream_events.return_value = [
        {"type": "status", "text": "designing"},
        {"type": "final", "reply": "hld", "skills_used": ["solution_architect"]},
    ]
    with patch("app.chat.orchestrator.registry.get", return_value=agentic):
        events = list(
            _stream_steps(
                "architect",
                [{"role": "user", "content": "architect"}],
                [PlanStep(skill="solution_architect", objective="design")],
                "policy",
                None,
                chat_id="c1",
            )
        )
    assert events[-1]["type"] == "final"


@pytest.mark.unit
def test_stream_steps_multi_includes_agentic_skill():
    agentic = MagicMock()
    agentic.is_agentic = True
    agentic.name = "solution_architect"
    agentic.stream_events.return_value = [
        {"type": "delta", "text": "d"},
        {"type": "final", "reply": "architected"},
    ]
    writer = _plain_skill("report_writer", "written")
    with patch(
        "app.chat.orchestrator.registry.get",
        side_effect=lambda name: {"solution_architect": agentic, "report_writer": writer}.get(name),
    ):
        with patch(
            "app.chat.orchestrator.azure_client.stream_chat",
            return_value=iter(["synth"]),
        ):
            events = list(
                _stream_steps(
                    "do both",
                    [{"role": "user", "content": "do both"}],
                    [
                        PlanStep(skill="solution_architect", objective="design"),
                        PlanStep(skill="report_writer", objective="write"),
                    ],
                    "policy",
                    None,
                )
            )
    assert events[-1]["reply"] == "synth"


@pytest.mark.unit
def test_gather_security_context_github_success_and_errors():
    with patch("app.chat.orchestrator._provider_block", return_value=None):
        with patch("app.chat.orchestrator.github_infra.is_connected", return_value=True):
            with patch(
                "app.chat.orchestrator.github_infra.build_code_report",
                return_value={"text": "LIVE GITHUB SECURITY"},
            ):
                text = _gather_security_context("find vulnerabilities", "p1")
    assert "LIVE GITHUB SECURITY" in text
    with patch("app.chat.orchestrator._provider_block", return_value=None):
        with patch("app.chat.orchestrator.github_infra.is_connected", return_value=True):
            with patch(
                "app.chat.orchestrator.github_infra.build_code_report",
                side_effect=GitHubApiError("denied"),
            ):
                failed = _gather_security_context("cve scan", "p1")
    assert "FETCH FAILED" in failed
    with patch("app.chat.orchestrator._provider_block", return_value=None):
        with patch("app.chat.orchestrator.github_infra.is_connected", return_value=True):
            with patch(
                "app.chat.orchestrator.github_infra.build_code_report",
                side_effect=GitHubConnectionError("missing"),
            ):
                empty = _gather_security_context("cve scan", "p1")
    assert "no connected provider" in empty.lower() or "SECURITY EVIDENCE" in empty


@pytest.mark.unit
def test_parse_metric_intent_llm_and_fallback():
    with patch(
        "app.chat.orchestrator.azure_client.chat",
        return_value=_llm(
            {
                "resource_types": ["container_app"],
                "resource_name": "all",
                "metrics": ["cpu"],
                "all_resources": True,
            }
        ),
    ):
        types, name, metrics = _parse_metric_intent("cpu for all container apps")
    assert types and "container_app" in types
    assert name is None
    assert metrics and "cpu" in metrics
    with patch("app.chat.orchestrator.azure_client.chat", side_effect=RuntimeError("down")):
        types, name, metrics = _parse_metric_intent("cpu last 24 hours")
    assert types
    assert metrics
    assert name is None


@pytest.mark.unit
def test_build_plan_drift_fallback_when_llm_returns_no_steps():
    with patch(
        "app.chat.orchestrator.azure_client.chat",
        return_value=_llm({"summary": "drift", "needs_clarification": False, "steps": []}),
    ):
        _summary, steps, questions = _build_plan(
            [{"role": "user", "content": "compare live azure vs terraform drift"}]
        )
    assert questions == []
    assert any(step.skill == "drift_auditor" for step in steps)


@pytest.mark.unit
def test_run_chat_agentic_plan_and_agent():
    skill = MagicMock()
    skill.is_agentic = True
    skill.name = "solution_architect"
    skill.run.return_value = SkillResult(skill="solution_architect", content="hld")
    skill.stream_events.return_value = [
        {"type": "final", "reply": "plan text", "plan": [{"skill": "report_writer", "objective": "x"}]}
    ]
    with patch("app.chat.orchestrator.registry.get", return_value=skill):
        with patch("app.chat.orchestrator._gather_project_topology", return_value="topo"):
            with patch("app.chat.orchestrator.provider_status_text", return_value="status"):
                planned = run_chat(
                    [{"role": "user", "content": "design"}],
                    "p1",
                    mode="plan",
                    skill="solution_architect",
                    chat_id="c1",
                )
                executed = run_chat(
                    [{"role": "user", "content": "design"}],
                    "p1",
                    mode="agent",
                    skill="solution_architect",
                    chat_id="c1",
                )
    assert planned.mode == "plan"
    assert executed.reply == "hld"


@pytest.mark.unit
@pytest.mark.infra
def test_run_chat_stream_plan_forced_and_clarification():
    with patch("app.chat.orchestrator._gather_project_topology", return_value="topo"):
        with patch("app.chat.orchestrator._gather_live_context", return_value=("live", [])):
            with patch("app.chat.orchestrator.provider_status_text", return_value="status"):
                with patch(
                    "app.chat.orchestrator._run_plan_mode",
                    return_value=ChatTurn(mode="plan", reply="step one then two"),
                ):
                    events = list(
                        run_chat_stream(
                            [{"role": "user", "content": "plan this"}],
                            "p1",
                            mode="plan",
                        )
                    )
    assert events[-1]["type"] == "final"
    skill = _plain_skill()
    with patch("app.chat.orchestrator.registry.get", return_value=skill):
        with patch("app.chat.orchestrator._gather_project_topology", return_value="topo"):
            with patch("app.chat.orchestrator._gather_live_context", return_value=("live", [])):
                with patch("app.chat.orchestrator.provider_status_text", return_value="status"):
                    with patch("app.chat.orchestrator._skill_deltas", return_value=iter(["ok"])):
                        forced = list(
                            run_chat_stream(
                                [{"role": "user", "content": "write"}],
                                "p1",
                                skill="report_writer",
                            )
                        )
    assert forced[-1]["skills_used"] == ["report_writer"]
    missing = list(
        run_chat_stream(
            [{"role": "user", "content": "x"}],
            "p1",
            skill="not_real",
        )
    )
    assert "not found" in missing[-1]["reply"]
    with patch("app.chat.orchestrator._gather_project_topology", return_value="topo"):
        with patch("app.chat.orchestrator._gather_live_context", return_value=("live", [])):
            with patch("app.chat.orchestrator.provider_status_text", return_value="status"):
                with patch(
                    "app.chat.orchestrator._build_plan",
                    return_value=("need", [], ["Which team?"]),
                ):
                    clarified = list(
                        run_chat_stream(
                            [{"role": "user", "content": "help"}],
                            "p1",
                        )
                    )
    assert clarified[-1].get("needs_clarification") is True


@pytest.mark.unit
def test_execute_plan_stream_gathers_context():
    skill = _plain_skill()
    with patch("app.chat.orchestrator.registry.get", return_value=skill):
        with patch("app.chat.orchestrator._gather_project_topology", return_value="topo"):
            with patch("app.chat.orchestrator._gather_live_context", return_value=("live", [])):
                with patch(
                    "app.chat.orchestrator._ensure_planned_context",
                    return_value=("live", []),
                ):
                    with patch("app.chat.orchestrator._skill_deltas", return_value=iter(["ok"])):
                        events = list(
                            execute_plan_stream(
                                [{"role": "user", "content": "go"}],
                                "p1",
                                [PlanStep(skill="report_writer", objective="write")],
                            )
                        )
    assert events[-1]["type"] == "final"


@pytest.mark.unit
def test_skill_args_security_and_vuln_triage():
    mapper = _skill_args("compliance_mapper", "task", "obj", "policy", "EVIDENCE", "memory")
    assert mapper.get("controls") == "EVIDENCE" or "operating_policy" in mapper
    triage = _skill_args("vuln_triage", "task", "obj", "policy", None)
    assert "findings" in triage
    generic = _skill_args("report_writer", "task", "obj", "policy", "live")
    assert generic["task"] == "task"


@pytest.mark.unit
def test_run_chat_stream_emits_status_before_gather_returns():
    import threading

    released = threading.Event()

    def slow_topology(*_a, **_k):
        released.wait(timeout=2)
        return "topo"

    with patch("app.chat.orchestrator._gather_project_topology", side_effect=slow_topology):
        with patch("app.chat.orchestrator._gather_live_context", return_value=("live", [])):
            with patch("app.chat.orchestrator.provider_status_text", return_value="status"):
                with patch(
                    "app.chat.orchestrator._build_plan",
                    return_value=("need", [], ["Which team?"]),
                ):
                    gen = run_chat_stream(
                        [{"role": "user", "content": "help"}],
                        "p1",
                    )
                    first = next(gen)
                    released.set()
                    rest = list(gen)
    assert first["type"] == "status"
    assert rest[-1]["type"] == "final"
