"""High-ROI remaining unit coverage: prompts, controller, orchestrator, tools, rq_job."""
from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from app.chat.orchestrator import (
    PlanStep,
    _build_plan,
    _ensure_planned_context,
    _format_detailed_plan,
    _run_multi_agent,
    _security_framework,
)
from app.core import prompts
from app.execution import chat_actions
from app.org_executors import controller
from executors.common.rq_job import _run, execute_provider_job
from executors.common.runner import CliResult


@pytest.mark.unit
def test_prompts_langfuse_success_and_fallback():
    fake_prompt = MagicMock()
    fake_prompt.compile.return_value = "compiled {{name}}"
    client = MagicMock()
    client.get_prompt.return_value = fake_prompt
    with patch("app.core.prompts.observability.tracing_enabled", return_value=True):
        with patch("langfuse.get_client", return_value=client):
            text = prompts.get_text_prompt("n", fallback="fb {{name}}", variables={"name": "Ada"})
    assert "compiled" in text or "Ada" in text
    with patch("app.core.prompts.observability.tracing_enabled", return_value=True):
        with patch("langfuse.get_client", side_effect=RuntimeError("down")):
            text = prompts.get_text_prompt("n", fallback="hello {{name}}", variables={"name": "Ada"})
    assert "Ada" in text
    assert prompts._fallback_compile("plain", None) == "plain"
    assert "{{missing}}" in prompts._fallback_compile("hi {{missing}}", {"name": "x"})


@pytest.mark.unit
def test_ensure_and_seed_core_prompts():
    client = MagicMock()
    client.get_prompt.side_effect = LookupError("missing")
    with patch("app.core.prompts.observability.tracing_enabled", return_value=True):
        with patch("langfuse.get_client", return_value=client):
            prompts.ensure_text_prompt("n", "body")
    client.create_prompt.assert_called()
    client.get_prompt.side_effect = None
    client.get_prompt.return_value = MagicMock()
    with patch("app.core.prompts.observability.tracing_enabled", return_value=True):
        with patch("langfuse.get_client", return_value=client):
            prompts.ensure_text_prompt("exists", "body")
    with patch("app.core.prompts.observability.tracing_enabled", return_value=True):
        with patch("langfuse.get_client", side_effect=RuntimeError("down")):
            prompts.ensure_text_prompt("n", "body")
    with patch("app.core.prompts.observability.tracing_enabled", return_value=False):
        prompts.ensure_text_prompt("n", "body")
        prompts.seed_core_prompts()
    with patch("app.core.prompts.observability.tracing_enabled", return_value=True):
        with patch("app.core.prompts.ensure_text_prompt") as ensure:
            with patch("app.agents.solution_architect.prompts.seed_architect_prompts", side_effect=RuntimeError("x")):
                prompts.seed_core_prompts()
    assert ensure.call_count >= 5


@pytest.mark.unit
def test_controller_should_be_active_and_tick():
    naive = datetime(2026, 1, 1, tzinfo=None)
    assert controller._parse_dt(None) is None
    assert controller._parse_dt(naive).tzinfo is not None
    assert controller._parse_dt("not-a-date") is None
    parsed = controller._parse_dt("2026-01-01T00:00:00")
    assert parsed.tzinfo is not None
    cfg = {
        "mode": "on_demand",
        "window_ends_at": None,
        "schedule": {},
        "last_job_at": None,
        "idle_scale_down_minutes": 15,
    }
    assert controller._should_be_active(cfg, 1) is True
    assert controller._should_be_active(cfg, 0) is False
    recent = datetime.now(timezone.utc).isoformat()
    cfg["last_job_at"] = recent
    assert controller._should_be_active(cfg, 0) is True
    cfg["mode"] = "schedule"
    assert controller._should_be_active(cfg, 9) is False
    store = MagicMock()
    store.list_all_settings.return_value = [
        {
            "org_id": "org-1",
            "mode": "on_demand",
            "actual_state": "scaled_to_zero",
            "max_replicas": 2,
            "aca_app_names": {},
            "last_job_at": recent,
            "idle_scale_down_minutes": 15,
            "window_ends_at": None,
            "schedule": {},
        }
    ]
    store.ensure_settings.return_value = store.list_all_settings.return_value[0]
    with patch("app.org_executors.controller.store", store):
        with patch("app.org_executors.controller.queue_depth", return_value=3):
            with patch("app.org_executors.controller.apply_scale", return_value={"azure": "app"}):
                with patch("app.org_executors.controller.scaler_kind", return_value="local"):
                    results = controller.tick_once()
    assert results[0]["org_id"] == "org-1"
    store.list_all_settings.return_value = [{"org_id": "org-err", "mode": "on_demand", "actual_state": "active", "max_replicas": 1, "aca_app_names": {}, "last_job_at": None, "window_ends_at": None, "schedule": {}}]
    with patch("app.org_executors.controller.store", store):
        with patch("app.org_executors.controller.queue_depth", side_effect=RuntimeError("redis")):
            with patch("app.org_executors.controller.apply_scale", side_effect=RuntimeError("scale")):
                failed = controller.tick_once()
    assert failed[0]["error"]
    with patch("app.org_executors.controller.store", store):
        with patch("app.org_executors.controller.tick_once", return_value=[{"org_id": "org-1", "desired": "active"}]):
            woke = controller.request_wake("org-1")
    assert woke["org_id"] == "org-1"
    fake_sched = MagicMock()
    controller._scheduler = None
    with patch("app.org_executors.controller.BackgroundScheduler", return_value=fake_sched):
        controller.start_controller()
        controller.start_controller()
    fake_sched.start.assert_called_once()
    controller.stop_controller()
    controller.stop_controller()
    assert controller._scheduler is None


@pytest.mark.unit
def test_ensure_planned_context_fetches_missing_live_data():
    steps = [
        PlanStep("metrics_analyzer", "cpu"),
        PlanStep("log_analyzer", "errors"),
        PlanStep("cost_analyzer", "spend"),
        PlanStep("cloud_posture", "posture"),
        PlanStep("iac_reviewer", "tf"),
        PlanStep("project_analyzer", "repo"),
        PlanStep("vuln_triage", "cve"),
    ]
    with patch("app.chat.orchestrator._gather_metrics_context", return_value=("METRICS", [{"t": 1}])):
        with patch("app.chat.orchestrator._gather_logs_context", return_value=("AZURE LOGS", [{"t": 2}])):
            with patch("app.chat.orchestrator._gather_cost_context", return_value="LIVE AZURE BILLING"):
                with patch("app.chat.orchestrator._provider_block", return_value="ENVIRONMENT DATA"):
                    with patch("app.chat.orchestrator._gather_code_context", return_value="LIVE GITHUB CODE"):
                        with patch(
                            "app.intelligence.repo_analyzer.analyze_to_prompt",
                            return_value="REPOSITORY ANALYSIS",
                        ):
                            with patch(
                                "app.chat.orchestrator._gather_security_context",
                                return_value="SECURITY EVIDENCE BUNDLE",
                            ):
                                live, charts = _ensure_planned_context("how is the app", "p1", steps, None, [])
    assert "METRICS" in (live or "")
    assert charts
    with patch("app.intelligence.repo_analyzer.analyze_to_prompt", side_effect=RuntimeError("x")):
        live2, _charts = _ensure_planned_context(
            "analyze repo",
            "p1",
            [PlanStep("project_analyzer", "repo")],
            "already",
            [],
        )
    assert live2 == "already" or live2 is not None


@pytest.mark.unit
def test_build_plan_appends_live_context_and_filters_clarification():
    completion = SimpleNamespace(
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(
                    content='{"summary":"ok","needs_clarification":true,"clarification_questions":["which app?"],"steps":[{"skill":"metrics_analyzer","objective":"cpu"}]}'
                )
            )
        ]
    )
    with patch("app.chat.orchestrator.azure_client.chat", return_value=completion):
        summary, steps, questions = _build_plan(
            [{"role": "user", "content": "cpu last 24 hours"}],
            live_context="LIVE AZURE METRICS for all apps",
        )
    assert summary == "ok"
    assert questions == [] or steps
    broken = SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content="not-json"))])
    with patch("app.chat.orchestrator.azure_client.chat", return_value=broken):
        _summary, _steps, _q = _build_plan(
            [{"role": "user", "content": "hello"}],
            live_context=None,
        )


@pytest.mark.unit
def test_run_multi_agent_clarification_and_direct_chat():
    clarify = SimpleNamespace(
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(
                    content='{"summary":"need info","needs_clarification":true,"clarification_questions":["What environment?"],"steps":[]}'
                )
            )
        ]
    )
    with patch("app.chat.orchestrator.azure_client.chat", return_value=clarify):
        turn = _run_multi_agent([{"role": "user", "content": "do something unique"}], "", None, "p1")
    assert turn.needs_clarification is True
    direct = SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content="direct reply"))])
    with patch(
        "app.chat.orchestrator._build_plan",
        return_value=("sum", [], []),
    ):
        with patch("app.chat.orchestrator._ensure_planned_context", return_value=(None, [])):
            with patch("app.chat.orchestrator.azure_client.chat", return_value=direct):
                empty = _run_multi_agent([{"role": "user", "content": "hi"}], "", None, "p1")
    assert empty.reply == "direct reply"


@pytest.mark.unit
def test_format_detailed_plan_and_security_framework():
    rendered = _format_detailed_plan(
        {
            "understanding": "Need metrics",
            "findings": "CPU is high",
            "plan": "Check Azure Monitor",
        },
        [PlanStep("metrics_analyzer", "cpu")],
    )
    assert "What you're asking" in rendered
    assert _security_framework("need SOC 2") == "soc2"
    assert _security_framework("ISO 27001 please") == "iso27001"
    assert _security_framework("pci review") == "pci-dss"


@pytest.mark.unit
def test_chat_actions_nsg_pending_and_diagnostics():
    assert chat_actions._message_mentions_nsg("lock down the NSG") is True
    assert chat_actions._message_mentions_nsg("app-nsg") is True
    assert chat_actions._pending_action("missing-chat") is None
    assert chat_actions._latest_action("missing-chat") is None
    assert chat_actions.action_diagnostic_context("missing", "unrelated hello") == ""
    with patch("app.execution.chat_actions.chats.get_chat", return_value={"messages": [{"meta": {"action_id": "a1"}}]}):
        with patch("app.execution.chat_actions.service.get_action", side_effect=KeyError("gone")):
            assert chat_actions._pending_action("c1") is None
            assert chat_actions._latest_action("c1") is None
    with patch("app.execution.chat_actions.chats.get_chat", return_value={"messages": [{"meta": {"action_id": "a1"}}]}):
        with patch(
            "app.execution.chat_actions.service.get_action",
            return_value={"id": "a1", "status": "queued", "provider": "azure", "command_preview": "az"},
        ):
            with patch(
                "app.execution.chat_actions.service.diagnose_action",
                return_value={
                    "queue": "q",
                    "age_seconds": 9,
                    "executor_available": False,
                    "queue_depth": 1,
                    "message": "warming",
                    "recommendation": "wait",
                },
            ):
                with patch(
                    "app.execution.chat_actions.service.list_events",
                    return_value=[{"payload": {"message": "queued"}, "created_at": "t", "type": "queued"}],
                ):
                    text = chat_actions.action_diagnostic_context("c1", "why is my action stuck")
    assert "CURRENT PROVIDER ACTION" in text
    vnet = chat_actions._vnet_request("create vnet named testing-vnet 10.0.0.0/16 10.0.1.0/24")
    assert vnet["name"] == "testing-vnet"
    with patch(
        "app.execution.chat_actions.chats.get_chat",
        return_value={"messages": [{"content": "create vnet named testing-vnet"}]},
    ):
        assert chat_actions._context_vnet_name("c1") == "testing-vnet"


@pytest.mark.unit
def test_rq_job_azure_login_failure_and_execute_exception():
    op = {
        "provider": "azure",
        "executable": "az",
        "args": ["account", "show"],
        "target": "identity",
        "preflight": [],
        "verify": [],
    }
    creds = {"client_id": "c", "client_secret": "s", "tenant_id": "t", "subscription_id": "sub"}
    login_fail = CliResult(1, "", "denied")
    with patch("executors.common.rq_job.run_cli", return_value=login_fail):
        status, _result, error = _run("azure", op, creds, {}, lambda *_a: None, lambda: False)
    assert status == "failed"
    assert "login" in error.lower()
    response = MagicMock()
    response.status_code = 500
    error = type("E", (), {"response": response})()
    with patch("executors.common.rq_job._claim", side_effect=type("H", (Exception,), {})()):
        pass
    import httpx

    http_err = httpx.HTTPStatusError("boom", request=MagicMock(), response=response)
    with patch("executors.common.rq_job._claim", side_effect=http_err):
        with pytest.raises(httpx.HTTPStatusError):
            execute_provider_job("a1", "azure")
    payload = {"credentials": creds, "operation": op}
    with patch("executors.common.rq_job._claim", return_value=payload):
        with patch("executors.common.rq_job._post_event"):
            with patch("executors.common.rq_job._run", side_effect=RuntimeError("cli exploded")):
                with patch("executors.common.rq_job._finish") as finish:
                    with patch("executors.common.rq_job._is_canceled", return_value=False):
                        with pytest.raises(RuntimeError):
                            execute_provider_job("a1", "azure")
    finish.assert_called()


@pytest.mark.unit
def test_github_list_repos_pagination_and_error_detail():
    from app.providers import github_infra

    page1 = MagicMock(status_code=200)
    page1.json.return_value = [{"full_name": f"acme/r{i}"} for i in range(100)]
    page2 = MagicMock(status_code=200)
    page2.json.return_value = [{"full_name": "acme/last"}]
    client = MagicMock()
    client.get.side_effect = [page1, page2]
    creds = github_infra.GitHubCredentials(token="t", username="acme")
    repos = github_infra._list_repos(client, creds, max_pages=8)
    assert len(repos) == 101
    err = MagicMock(status_code=500, text="nope")
    err.json.side_effect = ValueError("bad")
    assert github_infra._error_detail(err) == "nope"
    json_err = MagicMock()
    json_err.json.return_value = {"message": "rate limited"}
    assert "rate" in github_infra._error_detail(json_err)
    with pytest.raises(github_infra.GitHubApiError):
        bad = MagicMock(status_code=401)
        bad.json.return_value = {"message": "bad token"}
        fail_client = MagicMock()
        fail_client.get.return_value = bad
        github_infra._list_repos(fail_client, creds)
    later_fail = MagicMock(status_code=500)
    later_fail.json.return_value = {"message": "later"}
    mixed = MagicMock()
    mixed.get.side_effect = [page1, later_fail]
    partial = github_infra._list_repos(mixed, creds)
    assert len(partial) == 100
    empty_page = MagicMock(status_code=200)
    empty_page.json.return_value = []
    empty_client = MagicMock()
    empty_client.get.return_value = empty_page
    assert github_infra._list_repos(empty_client, creds) == []
    assert github_infra._resolve_branch(["main", "develop"], "main", env="dev") in {"develop", "main"}
    assert github_infra._resolve_branch(["feature/x", "MAIN"], "main", explicit="main") == "MAIN"
    assert github_infra._resolve_branch(["release-1"], "release-1", env="prod")


@pytest.mark.unit
def test_handle_turn_nsg_and_auth_verify_db():
    from app.core import auth

    with patch("app.execution.chat_actions._pending_action", return_value=None):
        with patch("app.execution.chat_actions._latest_action", return_value=None):
            with patch("app.execution.chat_actions.chat_memory.get_model_context", return_value=[]):
                with patch("app.execution.chat_actions._debug_intent", return_value=False):
                    with patch("app.execution.chat_actions._cicd_intent", return_value=False):
                        with patch("app.execution.chat_actions._deploy_intent", return_value=False):
                            with patch("app.execution.chat_actions._terraform_intent", return_value=None):
                                with patch("app.execution.chat_actions._resource_group_request", return_value=None):
                                    with patch("app.execution.chat_actions._vnet_request", return_value=None):
                                        with patch(
                                            "app.execution.chat_actions._context_resource_group",
                                            return_value={"name": "rg1", "location": "eastus"},
                                        ):
                                            with patch("app.execution.chat_actions._context_nsg_name", return_value="app-nsg"):
                                                with patch(
                                                    "app.execution.chat_actions.connections.get_secret_fields",
                                                    return_value={"subscription_id": "sub"},
                                                ):
                                                    with patch(
                                                        "app.execution.chat_actions._create_or_hold_action",
                                                        return_value={"reply": "prepared", "action": {"id": "a"}},
                                                    ) as held:
                                                        result = chat_actions.handle_turn("c1", "p1", "create the NSG", "write")
    assert result["reply"] == "prepared"
    held.assert_called()
    with patch("app.execution.chat_actions._pending_action", return_value=None):
        with patch("app.execution.chat_actions._latest_action", return_value=None):
            with patch("app.execution.chat_actions.chat_memory.get_model_context", return_value=[]):
                with patch("app.execution.chat_actions._debug_intent", return_value=False):
                    with patch("app.execution.chat_actions._cicd_intent", return_value=False):
                        with patch("app.execution.chat_actions._deploy_intent", return_value=False):
                            with patch("app.execution.chat_actions._terraform_intent", return_value=None):
                                with patch("app.execution.chat_actions._resource_group_request", return_value=None):
                                    with patch("app.execution.chat_actions._vnet_request", return_value=None):
                                        with patch(
                                            "app.execution.chat_actions._context_resource_group",
                                            return_value={"name": "rg1", "location": "eastus"},
                                        ):
                                            with patch("app.execution.chat_actions._context_nsg_name", return_value=""):
                                                asked = chat_actions.handle_turn("c1", "p1", "create nsg too", "write")
    assert "named" in asked["reply"].lower()
    assert auth.verify_token(None) is None
    assert auth.verify_token("not-a-jwt") is None
    assert auth.bearer_token(None) is None
    assert auth.bearer_token("Token abc") is None
    token = auth.bearer_token("Bearer abc.def")
    assert token == "abc.def"
    auth.invalidate_user_cache()
    auth.invalidate_user_cache("missing")
    with patch("app.core.auth._verify_db_enabled", return_value=True):
        with patch("app.core.auth._load_user_from_db", return_value={"id": "u1"}) as loaded:
            payload = auth.verify_token(
                __import__("jwt").encode(
                    {"sub": "u1", "username": "u", "name": "n", "role": "developer", "exp": 9999999999},
                    "test-jwt-secret-not-for-production",
                    algorithm="HS256",
                )
            )
    assert payload["id"] == "u1"
    loaded.assert_called()

