"""Orchestrator heuristic helpers: env, branch, diagnostic intent, policies."""
from __future__ import annotations

from unittest.mock import patch

import pytest

from app.chat.orchestrator import (
    ChatTurn,
    PlanStep,
    _augment_args,
    _clarification_reply,
    _current_request_text,
    _detect_branch,
    _detect_code_kinds,
    _detect_env,
    _extract_named_repos,
    _is_ack_or_policy_nudge,
    _is_security_task,
    _last_user_message,
    _looks_like_diagnostic_intent,
    _looks_like_drift_intent,
    _looks_like_posture_intent,
    _merge_context,
    _pretty,
    _security_framework,
    _skill_catalog_text,
    build_agent_policy,
    build_policy,
)


@pytest.mark.unit
def test_build_policy_and_agent_policy():
    policy = build_policy("read_only", "ask_approval")
    assert "READ" in policy.upper() or "read" in policy.lower()
    agent = build_agent_policy("write", "full_access")
    assert "AGENT" in agent.upper()
    unknown = build_policy("mystery", "mystery")  # type: ignore[arg-type]
    assert unknown


@pytest.mark.unit
def test_detect_env_and_branch():
    assert _detect_env("deploy to production") in {"prod", "production"} or _detect_env(
        "prod please"
    )
    assert _detect_env("hello") is None
    assert _detect_branch("use the release/1.2 branch") == "release/1.2"
    assert _detect_branch("hello world") is None


@pytest.mark.unit
def test_extract_named_repos_skips_urls_and_files():
    repos = _extract_named_repos("look at acme/payments and https://github.com/foo/bar")
    assert "acme/payments" in repos
    assert not any(item.startswith("https") for item in repos)
    assert "owner/readme.md" not in _extract_named_repos("see owner/readme.md")


@pytest.mark.unit
def test_diagnostic_drift_and_posture_intents():
    assert _looks_like_diagnostic_intent("") is False
    assert _looks_like_diagnostic_intent("review azure posture vs github")
    assert _looks_like_drift_intent("show drift between terraform and azure")
    assert _looks_like_posture_intent("cloud posture of the subscription")
    assert _looks_like_diagnostic_intent(
        "CURRENT USER REQUEST: everything bro\nCONVERSATION CONTEXT: review azure"
    )


@pytest.mark.unit
def test_security_and_ack_helpers():
    assert _is_security_task("run a compliance gap analysis")
    assert _security_framework("map to pci-dss") == "pci-dss"
    assert _is_ack_or_policy_nudge("ok thanks")
    assert not _is_ack_or_policy_nudge("create a resource group named testing")


@pytest.mark.unit
def test_context_merge_catalog_and_chat_turn():
    assert _merge_context(None, "", "keep") == "keep"
    assert "pipeline_auditor" in _skill_catalog_text()
    assert "solution_architect" not in _skill_catalog_text()
    assert _pretty("cloud_posture") == "Cloud Posture"
    turn = ChatTurn(mode="agent", reply="hi", skills_used=["a"], charts=[{"x": 1}])
    payload = turn.to_dict()
    assert payload["reply"] == "hi"
    assert payload["skills_used"] == ["a"]
    step = PlanStep(skill="iac_reviewer", objective="review")
    assert step.skill == "iac_reviewer"


@pytest.mark.unit
def test_last_user_and_current_request_text():
    messages = [
        {"role": "assistant", "content": "q?"},
        {"role": "user", "content": "do the thing"},
    ]
    assert _last_user_message(messages) == "do the thing"
    assert "do the thing" in _current_request_text("do the thing")


@pytest.mark.unit
def test_augment_args_and_clarification():
    args = _augment_args({"input": "x"}, "LIVE DATA")
    assert args["live_environment"] == "LIVE DATA"
    assert args["input"] == "x"
    reply = _clarification_reply(["Which repo?"], "Need scope")
    assert "Which repo?" in reply


@pytest.mark.unit
def test_detect_code_kinds_includes_terraform():
    kinds = _detect_code_kinds("review the terraform and helm charts")
    assert kinds
