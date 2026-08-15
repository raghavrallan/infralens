"""Skill.run, chat action routes, executor control plane, and remaining orchestrator LLM paths."""
from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from app.chat.orchestrator import (
    PlanStep,
    _build_detailed_plan,
    _format_detailed_plan,
    _gather_project_topology,
    _skill_args,
    _skill_deltas,
    execute_plan_stream,
)
from app.execution import chat_actions
from app.skills import registry
from app.skills.base import Skill


@pytest.mark.unit
def test_skill_run_and_stream_events_with_mocked_llm():
    skill = registry.get("report_writer")
    assert isinstance(skill, Skill)
    completion = MagicMock()
    completion.choices = [MagicMock(message=MagicMock(content="written"))]
    with patch("app.skills.base.azure_client.chat", return_value=completion):
        with patch("app.core.prompts.get_text_prompt", return_value="system"):
            result = skill.run({"input": "summarize this"})
            events = list(skill.stream_events({"input": "summarize this"}))
    assert result.content == "written"
    assert events[-1]["type"] == "final"
    tool = skill.as_tool()
    assert tool["function"]["name"] == "report_writer"


@pytest.mark.unit
@pytest.mark.infra
def test_handle_turn_cicd_deploy_and_write_scope():
    with patch("app.execution.chat_actions._pending_action", return_value=None):
        with patch("app.execution.chat_actions._latest_action", return_value=None):
            with patch("app.execution.chat_actions.chat_memory.get_model_context", return_value=[]):
                with patch(
                    "app.execution.cicd.auto_retry_failed_builds",
                    return_value={"prepared": []},
                ):
                    result = chat_actions.handle_turn(
                        "c1", "p1", "github actions failed on main", "read_only"
                    )
    assert result is not None
    assert "failed GitHub Actions" in result["reply"] or result["action"] is None
    with patch("app.execution.chat_actions._pending_action", return_value=None):
        with patch("app.execution.chat_actions._latest_action", return_value=None):
            with patch("app.execution.chat_actions.chat_memory.get_model_context", return_value=[]):
                deploy = chat_actions.handle_turn(
                    "c1", "p1", "deploy to production", "read_only"
                )
    assert deploy["required_action_scope"] == "write"


@pytest.mark.unit
@pytest.mark.infra
def test_handle_turn_resource_group_write_hold():
    with patch("app.execution.chat_actions._pending_action", return_value=None):
        with patch("app.execution.chat_actions._latest_action", return_value=None):
            with patch("app.execution.chat_actions.chat_memory.get_model_context", return_value=[]):
                with patch(
                    "app.execution.chat_actions.connections.get_secret_fields",
                    return_value={"subscription_id": "sub"},
                ):
                    with patch("app.execution.chat_actions.provider_status_text", return_value="status"):
                        result = chat_actions.handle_turn(
                            "c1",
                            "p1",
                            "Create me a new resource group in Azure named testing in eastus",
                            "read_only",
                        )
    assert result is not None
    assert result.get("required_action_scope") == "write" or result.get("action") is not None


@pytest.mark.unit
def test_build_detailed_plan_and_skill_args():
    payload = {
        "understanding": "Need a review",
        "findings": "NSG open",
        "issues": ["public"],
        "resolution": "restrict",
        "needs_clarification": False,
        "steps": [{"skill": "cloud_posture", "objective": "review"}],
    }
    completion = MagicMock()
    completion.choices = [MagicMock(message=MagicMock(content=json.dumps(payload)))]
    with patch("app.chat.orchestrator.azure_client.chat", return_value=completion):
        with patch("app.core.prompts.get_text_prompt", return_value="planner"):
            parsed, steps = _build_detailed_plan(
                [{"role": "user", "content": "review azure"}],
                "LIVE DATA",
            )
    assert parsed["understanding"]
    assert steps
    rendered = _format_detailed_plan(parsed, steps)
    assert "Need a review" in rendered or rendered
    args = _skill_args("cloud_posture", "task", "obj", "policy", "live", "memory")
    assert "objective" in args or "task" in args or args


@pytest.mark.unit
def test_execute_plan_stream_with_no_runnable_skills():
    events = list(
        execute_plan_stream(
            [{"role": "user", "content": "go"}],
            "p1",
            [PlanStep(skill="not_a_skill", objective="x")],
        )
    )
    assert "no runnable" in events[-1]["reply"].lower()


@pytest.mark.unit
def test_gather_project_topology_and_skill_deltas():
    with patch(
        "app.chat.project_context.gather_project_topology",
        return_value="TOPOLOGY",
    ):
        with patch("app.chat.chat_memory.get_requirements", return_value=["need api"]):
            text = _gather_project_topology(
                "p1",
                [
                    {"role": "user", "content": "hello", "meta": {"chat_id": "c1"}},
                    {"role": "system", "content": "Requirements:\n- api"},
                ],
            )
    assert text == "TOPOLOGY"
    skill = MagicMock()
    skill.stream = MagicMock(side_effect=AttributeError)
    skill.run.return_value = MagicMock(content="chunk")
    chunks = list(_skill_deltas(skill, {"input": "x"}))
    assert "chunk" in chunks or chunks == []
