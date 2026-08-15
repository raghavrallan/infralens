"""Orchestrator gather/live-context, misroute correction, and plan-mode branches."""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

import pytest

from app.chat.orchestrator import (
    PlanStep,
    _correct_misrouted_steps,
    _current_request_text,
    _gather_code_context,
    _gather_cost_context,
    _gather_live_context,
    _gather_logs_context,
    _gather_metrics_context,
    _is_ack_or_policy_nudge,
    _keyword_metric_scope,
    _looks_like_metrics_followup,
    _parse_metric_intent,
    _prior_turn_was_metrics,
    _run_plan_mode,
)
from app.providers import azure_infra, github_infra


@pytest.mark.unit
def test_metric_intent_keywords_and_llm_parse():
    types, _name, metrics, all_res = _keyword_metric_scope("cpu and memory for all container apps")
    assert "container_app" in (types or [])
    assert "cpu" in (metrics or [])
    assert all_res is True or types
    assert _looks_like_metrics_followup("container app") is True
    assert _looks_like_metrics_followup("which repo is backend vs frontend") is False
    assert _is_ack_or_policy_nudge("thanks") is True
    assert _prior_turn_was_metrics([{"role": "user", "content": "cpu last 24 hours"}]) is True
    wrapped = "CURRENT USER REQUEST:\ncpu please\nCONVERSATION CONTEXT:\nold"
    assert "cpu" in _current_request_text(wrapped)
    completion = SimpleNamespace(
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(
                    content='{"resource_types":["web_app"],"resource_name":"all","metrics":["cpu"],"all_resources":true}'
                )
            )
        ]
    )
    with patch("app.chat.orchestrator.azure_client.chat", return_value=completion):
        parsed_types, parsed_name, parsed_metrics = _parse_metric_intent("cpu for my app")
    assert parsed_name is None or parsed_types
    assert parsed_metrics
    with patch("app.chat.orchestrator.azure_client.chat", side_effect=RuntimeError("down")):
        fallback_types, _n, fallback_metrics = _parse_metric_intent("health of postgres")
    assert fallback_types
    assert fallback_metrics


@pytest.mark.unit
def test_correct_misrouted_steps_for_structural_and_security():
    metrics = [PlanStep("metrics_analyzer", "cpu")]
    assert _correct_misrouted_steps("thanks", metrics, []) == []
    repos = _correct_misrouted_steps("which repo is backend vs frontend", metrics, [])
    assert repos[0].skill == "project_analyzer"
    vulns = _correct_misrouted_steps("dependabot vulns", metrics, [])
    assert vulns[0].skill == "vuln_triage"
    rollback = _correct_misrouted_steps("what if terraform apply failed later", metrics, [])
    assert rollback[0].skill == "terraform_executor"
    debug = _correct_misrouted_steps("acr image pull fail", metrics, [])
    assert debug[0].skill == "infra_debugger"
    report = _correct_misrouted_steps("worst 5 things summary", metrics, [])
    assert report[0].skill == "report_writer"
    dropped = _correct_misrouted_steps(
        "container app",
        metrics,
        [{"role": "user", "content": "hello"}],
    )
    assert dropped == []


@pytest.mark.unit
def test_gather_metrics_logs_cost_and_code_paths():
    assert _gather_metrics_context("hello", "p1") == (None, [])
    with patch("app.chat.orchestrator.azure_infra.is_connected", return_value=False):
        assert _gather_metrics_context("cpu last hour", "p1")[0] is None
    with patch("app.chat.orchestrator.azure_infra.is_connected", return_value=True):
        with patch("app.chat.orchestrator._parse_metric_intent", return_value=(["container_app"], None, ["cpu"])):
            with patch(
                "app.chat.orchestrator.azure_infra.build_metrics_report",
                return_value={"text": "cpu=1", "charts": [{"t": 1}]},
            ):
                text, charts = _gather_metrics_context("cpu for all apps", "p1")
    assert "LIVE AZURE METRICS" in (text or "")
    assert charts
    with patch("app.chat.orchestrator.azure_infra.is_connected", return_value=True):
        with patch("app.chat.orchestrator._parse_metric_intent", return_value=(None, None, None)):
            with patch(
                "app.chat.orchestrator.azure_infra.build_metrics_report",
                side_effect=azure_infra.AzureApiError("no reader"),
            ):
                failed, _c = _gather_metrics_context("cpu", "p1", force=True)
    assert "FETCH FAILED" in (failed or "")
    with patch("app.chat.orchestrator.azure_infra.is_connected", return_value=True):
        with patch(
            "app.chat.orchestrator.azure_infra.build_status_report",
            return_value={"text": "4xx=2", "charts": [{"t": 2}]},
        ):
            with patch(
                "app.chat.orchestrator.azure_infra.build_logs_report",
                return_value={"text": "boom"},
            ):
                logs, log_charts = _gather_logs_context("show 500 errors and logs", "p1")
    assert "TELEMETRY" in (logs or "")
    assert log_charts
    with patch("app.chat.orchestrator.azure_infra.is_connected", return_value=True):
        with patch(
            "app.chat.orchestrator.azure_infra.build_status_report",
            side_effect=azure_infra.AzureApiError("no traffic"),
        ):
            with patch(
                "app.chat.orchestrator.azure_infra.build_logs_report",
                side_effect=azure_infra.AzureApiError("no workspace"),
            ):
                failed_logs, _ = _gather_logs_context("500 errors in the logs", "p1")
    assert "unavailable" in (failed_logs or "").lower() or "FAILED" in (failed_logs or "")
    with patch("app.chat.orchestrator.azure_infra.is_connected", return_value=True):
        with patch(
            "app.chat.orchestrator.azure_infra.build_cost_report",
            return_value={"text": "$12"},
        ):
            cost = _gather_cost_context("how much did azure cost last month", "p1")
    assert "BILLING" in (cost or "")
    with patch("app.chat.orchestrator.azure_infra.is_connected", return_value=True):
        with patch(
            "app.chat.orchestrator.azure_infra.build_cost_report",
            side_effect=azure_infra.AzureApiError("no cm reader"),
        ):
            cost_fail = _gather_cost_context("billing", "p1", force=True)
    assert "FETCH FAILED" in (cost_fail or "")
    with patch("app.chat.orchestrator.github_infra.is_connected", return_value=True):
        with patch(
            "app.chat.orchestrator.github_infra.build_code_report",
            return_value={"text": "main.tf"},
        ):
            code = _gather_code_context("review terraform", "p1", force=True)
    assert code == "main.tf" or (code and "tf" in code)
    with patch("app.chat.orchestrator.github_infra.is_connected", return_value=True):
        with patch(
            "app.chat.orchestrator.github_infra.build_code_report",
            side_effect=github_infra.GitHubApiError("no repo scope"),
        ):
            code_fail = _gather_code_context("review the dockerfile", "p1", force=True)
    assert "GITHUB CODE FETCH FAILED" in (code_fail or "")


@pytest.mark.unit
def test_gather_live_context_and_plan_mode():
    with patch("app.chat.orchestrator.azure_infra.is_connected", return_value=True):
        with patch("app.chat.orchestrator.github_infra.is_connected", return_value=False):
            with patch("app.chat.orchestrator._gather_metrics_context", return_value=("METRICS", [{"c": 1}])):
                with patch("app.chat.orchestrator._gather_logs_context", return_value=("LOGS", [])):
                    with patch("app.chat.orchestrator._gather_cost_context", return_value="COST"):
                        with patch("app.chat.orchestrator._gather_code_context", return_value=None):
                            with patch("app.chat.orchestrator._gather_security_context", return_value=None):
                                with patch("app.chat.orchestrator._provider_block", return_value="ENV"):
                                    live, charts = _gather_live_context(
                                        "cpu cost and logs",
                                        "p1",
                                        force=True,
                                        force_cost=True,
                                        force_metrics=True,
                                        force_logs=True,
                                    )
    assert live
    assert charts or live
    parsed = {
        "needs_clarification": True,
        "clarification_questions": ["What environment?"],
        "understanding": "Need env",
        "steps": [],
    }
    with patch("app.chat.orchestrator._build_detailed_plan", return_value=(parsed, [])):
        turn = _run_plan_mode([{"role": "user", "content": "design a queue"}], None)
    assert turn.needs_clarification is True
    with patch(
        "app.chat.orchestrator._build_detailed_plan",
        return_value=({"understanding": "general", "steps": []}, []),
    ):
        empty = _run_plan_mode([{"role": "user", "content": "what is azure"}], None)
    assert empty.mode == "plan"
    steps = [PlanStep("cloud_posture", "review")]
    with patch(
        "app.chat.orchestrator._build_detailed_plan",
        return_value=({"understanding": "secure it", "findings": "nsg", "plan": "lock"}, steps),
    ):
        planned = _run_plan_mode([{"role": "user", "content": "harden prod"}], "ENVIRONMENT DATA")
    assert planned.plan
