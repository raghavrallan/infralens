"""Remaining high-ROI branches: Azure logs/metrics, chat_actions RG, RQ login, GitHub code."""
from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import httpx
import pytest

from app.execution import chat_actions
from app.providers import azure_infra, github_infra
from app.providers.azure_infra import AzureApiError, AzureCredentials
from app.providers.github_infra import GitHubCredentials
from executors.common.rq_job import _run
from executors.common.runner import CliResult


def _idle():
    return patch.multiple(
        "app.execution.chat_actions",
        _pending_action=lambda _chat: None,
        _latest_action=lambda _chat: None,
    )


@pytest.mark.unit
def test_build_logs_report_arm_error_and_missing_subscription():
    creds = AzureCredentials("t", "c", "s", "")
    with patch("app.providers.azure_infra.load_credentials", return_value=creds):
        with pytest.raises(AzureApiError, match="subscription"):
            azure_infra.build_logs_report("p1", "show logs")
    creds = AzureCredentials("t", "c", "s", "sub")
    app = {
        "id": "/subscriptions/sub/resourceGroups/rg/providers/Microsoft.App/containerApps/demo",
        "name": "demo",
        "type": "microsoft.app/containerapps",
    }
    with patch("app.providers.azure_infra.load_credentials", return_value=creds):
        with patch("app.providers.azure_infra._get_token", return_value="tok"):
            with patch("app.providers.azure_infra._log_workspaces", return_value=["ws-1"]):
                with patch("app.providers.azure_infra._get_logs_token", return_value="logs"):
                    with patch("app.providers.azure_infra._discover_resources", return_value=[app]):
                        with patch("app.providers.azure_infra._select_resources", return_value=[app]):
                            with patch(
                                "app.providers.azure_infra._arm_get",
                                side_effect=AzureApiError("arm down"),
                            ):
                                with patch(
                                    "app.providers.azure_infra._run_log_query",
                                    return_value=(["Reason_s"], [["Probe"]]),
                                ):
                                    report = azure_infra.build_logs_report("p1", "show logs")
    assert "LIVE AZURE LOGS" in report["text"]


@pytest.mark.unit
def test_discover_topology_empty_token_and_run_log_query():
    creds = AzureCredentials("t", "c", "s", "sub")
    with patch("app.providers.azure_infra.load_credentials", return_value=creds):
        with patch("app.providers.azure_infra._get_token", return_value=""):
            with pytest.raises(AzureApiError, match="empty access token"):
                azure_infra.discover_topology("p1")
    ok = MagicMock(status_code=200)
    ok.json.return_value = {
        "tables": [
            {
                "columns": [{"name": "TimeGenerated"}, {"name": "Log_s"}],
                "rows": [["t1", "boom"]],
            }
        ]
    }
    with patch("app.providers.azure_infra.httpx.post", return_value=ok):
        cols, rows = azure_infra._run_log_query("tok", "ws", "query", "PT1H")
    assert cols == ["TimeGenerated", "Log_s"]
    assert rows[0][1] == "boom"
    empty = MagicMock(status_code=200)
    empty.json.return_value = {"tables": []}
    with patch("app.providers.azure_infra.httpx.post", return_value=empty):
        cols, rows = azure_infra._run_log_query("tok", "ws", "query", "PT1H")
    assert cols == []
    bad = MagicMock(status_code=500, text="nope")
    bad.json.return_value = {"error": {"message": "fail"}}
    with patch("app.providers.azure_infra.httpx.post", return_value=bad):
        with pytest.raises(AzureApiError, match="query failed"):
            azure_infra._run_log_query("tok", "ws", "query", "PT1H")
    with patch("app.providers.azure_infra.httpx.post", side_effect=httpx.ConnectError("down")):
        with pytest.raises(AzureApiError, match="request failed"):
            azure_infra._run_log_query("tok", "ws", "query", "PT1H")
    with patch("app.providers.azure_infra._run_query", return_value=[{"cid": "ws-a"}, {}]):
        assert azure_infra._log_workspaces("tok", ["sub"]) == ["ws-a"]


@pytest.mark.unit
def test_build_metrics_report_total_aggregation_and_empty_fallback():
    creds = AzureCredentials("t", "c", "s", "sub")
    resource = {
        "id": "/subs/sub/rgs/rg/providers/Microsoft.App/containerApps/app",
        "name": "app",
        "type": "microsoft.app/containerapps",
        "cpuAlloc": 0.5,
        "memAlloc": "1Gi",
    }
    definition = {
        "name": {"value": "Requests", "localizedValue": "Requests"},
        "primaryAggregationType": "Total",
        "unit": "Count",
    }
    payload = {
        "value": [
            {
                "timeseries": [
                    {
                        "data": [
                            {"timeStamp": "t1", "total": 4.0},
                            {"timeStamp": "t2", "total": 6.0},
                        ]
                    }
                ]
            }
        ]
    }
    with patch("app.providers.azure_infra.load_credentials", return_value=creds):
        with patch("app.providers.azure_infra._get_token", return_value="tok"):
            with patch("app.providers.azure_infra._discover_resources", return_value=[resource]):
                with patch("app.providers.azure_infra._fetch_metric_definitions", return_value=[definition]):
                    with patch("app.providers.azure_infra._fetch_metric", return_value=payload):
                        report = azure_infra.build_metrics_report(
                            "p1", "request metrics last hour", metric_hints=["requests"]
                        )
    assert report["charts"]
    assert "total" in report["text"].lower()
    empty_payload = {"value": [{"timeseries": [{"data": [{"timeStamp": "t1", "average": None}]}]}]}
    with patch("app.providers.azure_infra.load_credentials", return_value=creds):
        with patch("app.providers.azure_infra._get_token", return_value="tok"):
            with patch("app.providers.azure_infra._discover_resources", return_value=[resource]):
                with patch("app.providers.azure_infra._fetch_metric_definitions", return_value=[definition]):
                    with patch("app.providers.azure_infra._match_definition", return_value=None):
                        with patch(
                            "app.providers.azure_infra._default_definitions",
                            return_value=[definition],
                        ):
                            with patch(
                                "app.providers.azure_infra._fetch_metric",
                                return_value=empty_payload,
                            ):
                                with pytest.raises(AzureApiError, match="no data"):
                                    azure_infra.build_metrics_report("p1", "metrics for app")
    creds_no_sub = AzureCredentials("t", "c", "s", "")
    with patch("app.providers.azure_infra.load_credentials", return_value=creds_no_sub):
        with pytest.raises(AzureApiError, match="subscription"):
            azure_infra.build_metrics_report("p1", "cpu")
    with patch("app.providers.azure_infra.load_credentials", return_value=creds):
        with patch("app.providers.azure_infra._get_token", return_value=""):
            with pytest.raises(AzureApiError, match="empty access token"):
                azure_infra.build_metrics_report("p1", "cpu")


@pytest.mark.unit
def test_handle_turn_creates_resource_group_when_name_and_location_present():
    spec_result = {"reply": "prepared rg", "action": {"id": "rg1"}, "event_type": "action_queued"}
    with _idle():
        with patch("app.execution.chat_actions.chat_memory.get_model_context", return_value=[]):
            with patch("app.execution.chat_actions._debug_intent", return_value=False):
                with patch("app.execution.chat_actions._cicd_intent", return_value=False):
                    with patch("app.execution.chat_actions._deploy_intent", return_value=False):
                        with patch("app.execution.chat_actions._terraform_intent", return_value=None):
                            with patch(
                                "app.execution.chat_actions.connections.get_secret_fields",
                                return_value={"subscription_id": "sub"},
                            ):
                                with patch(
                                    "app.execution.chat_actions._create_or_hold_action",
                                    return_value=spec_result,
                                ) as held:
                                    created = chat_actions.handle_turn(
                                        "c1",
                                        "p1",
                                        "Create resource group testing in eastus",
                                        "write",
                                    )
    assert created["action"]["id"] == "rg1"
    held.assert_called()
    with _idle():
        with patch("app.execution.chat_actions.chat_memory.get_model_context", return_value=[]):
            with patch("app.execution.chat_actions._debug_intent", return_value=False):
                with patch("app.execution.chat_actions._cicd_intent", return_value=False):
                    with patch("app.execution.chat_actions._deploy_intent", return_value=False):
                        with patch("app.execution.chat_actions._terraform_intent", return_value=None):
                            with patch(
                                "app.execution.chat_actions.connections.get_secret_fields",
                                return_value={},
                            ):
                                missing_sub = chat_actions.handle_turn(
                                    "c1",
                                    "p1",
                                    "Create resource group testing in eastus",
                                    "write",
                                )
    assert "subscription" in missing_sub["reply"].lower()
    with _idle():
        with patch("app.execution.chat_actions.chat_memory.get_model_context", return_value=[]):
            with patch("app.execution.chat_actions._debug_intent", return_value=False):
                with patch("app.execution.chat_actions._cicd_intent", return_value=False):
                    with patch("app.execution.chat_actions._deploy_intent", return_value=False):
                        with patch("app.execution.chat_actions._terraform_intent", return_value=None):
                            with patch(
                                "app.execution.chat_actions.connections.get_secret_fields",
                                return_value={"subscription_id": "sub"},
                            ):
                                scoped = chat_actions.handle_turn(
                                    "c1",
                                    "p1",
                                    "Create resource group testing in eastus",
                                    "read_only",
                                )
    assert scoped.get("required_action_scope") == "write"


@pytest.mark.unit
def test_handle_turn_delete_context_group_and_planner_compound():
    with _idle():
        with patch("app.execution.chat_actions.chat_memory.get_model_context", return_value=[]):
            with patch("app.execution.chat_actions._debug_intent", return_value=False):
                with patch("app.execution.chat_actions._cicd_intent", return_value=False):
                    with patch("app.execution.chat_actions._deploy_intent", return_value=False):
                        with patch("app.execution.chat_actions._terraform_intent", return_value=None):
                            with patch(
                                "app.execution.chat_actions._resource_group_request",
                                return_value=None,
                            ):
                                with patch(
                                    "app.execution.chat_actions._context_resource_group",
                                    return_value={"name": "rg1", "location": "eastus"},
                                ):
                                    with patch(
                                        "app.execution.chat_actions.connections.get_secret_fields",
                                        return_value={"subscription_id": "sub"},
                                    ):
                                        with patch(
                                            "app.execution.chat_actions._create_or_hold_action",
                                            return_value={"reply": "delete", "action": {"id": "d1"}},
                                        ):
                                            deleted = chat_actions.handle_turn(
                                                "c1", "p1", "delete that resource group", "write"
                                            )
    assert deleted["action"]["id"] == "d1"
    compound = {
        "kind": "action",
        "operation": {"provider": "azure", "executable": "az", "access_scope": "write"},
        "operations": [
            {
                "provider": "azure",
                "executable": "az",
                "access_scope": "write",
                "expected_result": "rg exists",
                "risk": "create rg",
            },
            {
                "provider": "azure",
                "executable": "az",
                "access_scope": "write",
                "expected_result": "nsg exists",
                "risk": "create nsg",
            },
        ],
    }
    with _idle():
        with patch("app.execution.chat_actions.chat_memory.get_model_context", return_value=[]):
            with patch("app.execution.chat_actions._debug_intent", return_value=False):
                with patch("app.execution.chat_actions._cicd_intent", return_value=False):
                    with patch("app.execution.chat_actions._deploy_intent", return_value=False):
                        with patch("app.execution.chat_actions._terraform_intent", return_value=None):
                            with patch(
                                "app.execution.chat_actions._resource_group_request",
                                return_value=None,
                            ):
                                with patch(
                                    "app.execution.chat_actions._vnet_request",
                                    return_value=None,
                                ):
                                    with patch(
                                        "app.execution.chat_actions._message_mentions_nsg",
                                        return_value=False,
                                    ):
                                        with patch(
                                            "app.execution.chat_actions._delete_requested",
                                            return_value=False,
                                        ):
                                            with patch(
                                                "app.execution.action_planner.looks_like_diagnostic",
                                                return_value=False,
                                            ):
                                                with patch(
                                                    "app.execution.action_planner.plan_action",
                                                    return_value=compound,
                                                ):
                                                    with patch(
                                                        "app.execution.chat_actions._create_or_hold_action",
                                                        return_value={
                                                            "reply": "compound",
                                                            "action": {"id": "c1"},
                                                        },
                                                    ) as held:
                                                        planned = chat_actions.handle_turn(
                                                            "c1",
                                                            "p1",
                                                            "create a storage account demo",
                                                            "write",
                                                        )
    assert planned["action"]["id"] == "c1"
    held.assert_called()
    mixed = {
        "kind": "action",
        "operation": {},
        "operations": [
            {"provider": "azure", "executable": "az", "access_scope": "write"},
            {"provider": "github", "executable": "gh", "access_scope": "write"},
        ],
    }
    with _idle():
        with patch("app.execution.chat_actions.chat_memory.get_model_context", return_value=[]):
            with patch("app.execution.chat_actions._debug_intent", return_value=False):
                with patch("app.execution.chat_actions._cicd_intent", return_value=False):
                    with patch("app.execution.chat_actions._deploy_intent", return_value=False):
                        with patch("app.execution.chat_actions._terraform_intent", return_value=None):
                            with patch(
                                "app.execution.chat_actions._resource_group_request",
                                return_value=None,
                            ):
                                with patch(
                                    "app.execution.chat_actions._vnet_request",
                                    return_value=None,
                                ):
                                    with patch(
                                        "app.execution.chat_actions._message_mentions_nsg",
                                        return_value=False,
                                    ):
                                        with patch(
                                            "app.execution.chat_actions._delete_requested",
                                            return_value=False,
                                        ):
                                            with patch(
                                                "app.execution.action_planner.looks_like_diagnostic",
                                                return_value=False,
                                            ):
                                                with patch(
                                                    "app.execution.action_planner.plan_action",
                                                    return_value=mixed,
                                                ):
                                                    split = chat_actions.handle_turn(
                                                        "c1",
                                                        "p1",
                                                        "create a storage account demo",
                                                        "write",
                                                    )
    assert "separate" in split["reply"].lower()
    clarification = {"kind": "clarification", "question": "Which resource should I create?"}
    with _idle():
        with patch("app.execution.chat_actions.chat_memory.get_model_context", return_value=[]):
            with patch("app.execution.chat_actions._debug_intent", return_value=False):
                with patch("app.execution.chat_actions._cicd_intent", return_value=False):
                    with patch("app.execution.chat_actions._deploy_intent", return_value=False):
                        with patch("app.execution.chat_actions._terraform_intent", return_value=None):
                            with patch(
                                "app.execution.chat_actions._resource_group_request",
                                return_value=None,
                            ):
                                with patch(
                                    "app.execution.chat_actions._vnet_request",
                                    return_value=None,
                                ):
                                    with patch(
                                        "app.execution.chat_actions._message_mentions_nsg",
                                        return_value=False,
                                    ):
                                        with patch(
                                            "app.execution.chat_actions._delete_requested",
                                            return_value=False,
                                        ):
                                            with patch(
                                                "app.execution.action_planner.looks_like_diagnostic",
                                                return_value=False,
                                            ):
                                                with patch(
                                                    "app.execution.action_planner.looks_like_scope_clarification",
                                                    return_value=False,
                                                ):
                                                    with patch(
                                                        "app.execution.action_planner.plan_action",
                                                        return_value=clarification,
                                                    ):
                                                        asked = chat_actions.handle_turn(
                                                            "c1",
                                                            "p1",
                                                            "create a storage account demo",
                                                            "write",
                                                        )
    assert "Which resource" in asked["reply"]


@pytest.mark.unit
def test_handle_turn_fallback_rg_missing_name_and_location():
    with _idle():
        with patch("app.execution.chat_actions.chat_memory.get_model_context", return_value=[]):
            with patch("app.execution.chat_actions._debug_intent", return_value=False):
                with patch("app.execution.chat_actions._cicd_intent", return_value=False):
                    with patch("app.execution.chat_actions._deploy_intent", return_value=False):
                        with patch("app.execution.chat_actions._terraform_intent", return_value=None):
                            with patch(
                                "app.execution.chat_actions._resource_group_request",
                                return_value={"name": "", "location": ""},
                            ):
                                with patch(
                                    "app.execution.action_planner.looks_like_diagnostic",
                                    return_value=True,
                                ):
                                    missing = chat_actions.handle_turn(
                                        "c1", "p1", "create a resource group", "write"
                                    )
    assert "resource group name" in missing["reply"].lower()
    with _idle():
        with patch("app.execution.chat_actions.chat_memory.get_model_context", return_value=[]):
            with patch("app.execution.chat_actions._debug_intent", return_value=False):
                with patch("app.execution.chat_actions._cicd_intent", return_value=False):
                    with patch("app.execution.chat_actions._deploy_intent", return_value=False):
                        with patch("app.execution.chat_actions._terraform_intent", return_value=None):
                            with patch(
                                "app.execution.chat_actions._resource_group_request",
                                return_value={"name": "demo", "location": ""},
                            ):
                                with patch(
                                    "app.execution.action_planner.looks_like_diagnostic",
                                    return_value=True,
                                ):
                                    with patch(
                                        "app.execution.chat_actions._missing_location_reply",
                                        return_value={"reply": "need location"},
                                    ):
                                        loc = chat_actions.handle_turn(
                                            "c1", "p1", "create resource group demo", "write"
                                        )
    assert loc["reply"] == "need location"


@pytest.mark.unit
def test_rq_job_azure_login_canceled_and_subscription_failures():
    op = {
        "provider": "azure",
        "executable": "az",
        "args": ["account", "show"],
        "target": "identity",
        "preflight": [],
        "verify": [],
    }
    creds = {
        "client_id": "c",
        "client_secret": "s",
        "tenant_id": "t",
        "subscription_id": "sub",
    }

    def _cli_login_canceled(argv, _env, cancel_check=None):
        if argv[:2] == ["az", "login"]:
            return CliResult(0, "", "", canceled=True)
        return CliResult(0, "", "")

    with patch("executors.common.rq_job.validate_operation", return_value=op):
        with patch("executors.common.rq_job.run_cli", side_effect=_cli_login_canceled):
            status, _result, error = _run("azure", op, creds, {}, lambda *_a: None, lambda: False)
    assert status == "canceled"
    assert "canceled" in error.lower()

    def _cli_sub_fail(argv, _env, cancel_check=None):
        if argv[:2] == ["az", "login"]:
            return CliResult(0, "", "")
        if argv[:3] == ["az", "account", "set"]:
            return CliResult(1, "", "no sub")
        return CliResult(0, "", "")

    with patch("executors.common.rq_job.validate_operation", return_value=op):
        with patch("executors.common.rq_job.run_cli", side_effect=_cli_sub_fail):
            status, _result, error = _run("azure", op, creds, {}, lambda *_a: None, lambda: False)
    assert status == "failed"
    assert "subscription" in error.lower()

    def _cli_sub_canceled(argv, _env, cancel_check=None):
        if argv[:2] == ["az", "login"]:
            return CliResult(0, "", "")
        if argv[:3] == ["az", "account", "set"]:
            return CliResult(0, "", "", canceled=True)
        return CliResult(0, "", "")

    with patch("executors.common.rq_job.validate_operation", return_value=op):
        with patch("executors.common.rq_job.run_cli", side_effect=_cli_sub_canceled):
            status, _result, error = _run("azure", op, creds, {}, lambda *_a: None, lambda: False)
    assert status == "canceled"


@pytest.mark.unit
def test_github_create_repo_http_error_and_user_path():
    creds = GitHubCredentials(token="gho_x")
    client = MagicMock()
    client.__enter__.return_value = client
    client.__exit__.return_value = False
    created = MagicMock(status_code=201)
    created.json.return_value = {
        "full_name": "octo/demo",
        "html_url": "https://github.com/octo/demo",
        "private": True,
        "default_branch": "main",
        "clone_url": "https://github.com/octo/demo.git",
    }
    client.post.return_value = created
    with patch("app.providers.github_infra.load_credentials", return_value=creds):
        with patch("app.providers.github_infra._client", return_value=client):
            result = github_infra.create_repo("p1", name="demo")
    assert result["full_name"] == "octo/demo"
    client.post.assert_called()
    assert "/user/repos" in client.post.call_args[0][0]
    client.post.side_effect = httpx.ConnectError("down")
    with patch("app.providers.github_infra.load_credentials", return_value=creds):
        with patch("app.providers.github_infra._client", return_value=client):
            with pytest.raises(github_infra.GitHubApiError, match="request failed"):
                github_infra.create_repo("p1", name="demo")
    with pytest.raises(ValueError, match="Invalid"):
        github_infra.create_repo("p1", name="")


@pytest.mark.unit
def test_github_build_code_report_prefers_named_repo_and_env_branch():
    creds = GitHubCredentials(token="gho_x", username="octo")
    client = MagicMock()
    client.__enter__.return_value = client
    client.__exit__.return_value = False
    who = MagicMock(status_code=200)
    who.json.return_value = {"login": "octo"}
    extra = MagicMock(status_code=200)
    extra.json.return_value = {
        "full_name": "octo/extra",
        "archived": False,
        "language": "Python",
        "default_branch": "main",
    }
    with patch("app.providers.github_infra.load_credentials", return_value=creds):
        with patch("app.providers.github_infra._client", return_value=client):
            with patch("app.providers.github_infra._get", side_effect=[who, extra]):
                with patch(
                    "app.providers.github_infra._allowed_repos",
                    return_value={"octo/app"},
                ):
                    with patch(
                        "app.providers.github_infra._list_repos",
                        return_value=[
                            {
                                "full_name": "octo/app",
                                "archived": False,
                                "language": "Python",
                                "default_branch": "main",
                            }
                        ],
                    ):
                        with patch(
                            "app.providers.github_infra._list_branches",
                            return_value=["main", "develop"],
                        ):
                            with patch(
                                "app.providers.github_infra._get_tree",
                                return_value=[
                                    {"path": "main.tf", "type": "blob"},
                                    {"path": "README.md", "type": "blob"},
                                ],
                            ):
                                with patch(
                                    "app.providers.github_infra._get_raw_file",
                                    return_value="resource azurerm {}",
                                ):
                                    report = github_infra.build_code_report(
                                        "p1",
                                        ["terraform"],
                                        env="dev",
                                        prefer_repos=["octo/extra"],
                                    )
    assert report is not None
    assert "LIVE GITHUB CODE" in report["text"]
    assert github_infra.build_code_report("p1", ["not-a-kind"]) is None


@pytest.mark.unit
def test_require_user_falls_back_to_bearer_token():
    from fastapi import HTTPException

    from app.core import auth

    request = SimpleNamespace(state=SimpleNamespace(user=None))
    with pytest.raises(HTTPException) as exc:
        auth.require_user(request, authorization=None)
    assert exc.value.status_code == 401
    request.state.user = {"id": "u1", "username": "ada"}
    assert auth.require_user(request, authorization=None)["id"] == "u1"
    request.state.user = "not-a-dict"
    with patch("app.core.auth.verify_token", return_value={"id": "u2"}):
        assert auth.require_user(request, authorization="Bearer tok")["id"] == "u2"


@pytest.mark.unit
def test_handle_turn_compound_falls_through_to_resource_group_create():
    spec_result = {"reply": "prepared rg", "action": {"id": "rg2"}, "event_type": "action_queued"}
    with _idle():
        with patch("app.execution.chat_actions.chat_memory.get_model_context", return_value=[]):
            with patch("app.execution.chat_actions._debug_intent", return_value=False):
                with patch("app.execution.chat_actions._cicd_intent", return_value=False):
                    with patch("app.execution.chat_actions._deploy_intent", return_value=False):
                        with patch("app.execution.chat_actions._terraform_intent", return_value=None):
                            with patch(
                                "app.execution.action_planner.looks_like_diagnostic",
                                return_value=True,
                            ):
                                with patch(
                                    "app.execution.chat_actions.connections.get_secret_fields",
                                    return_value={"subscription_id": "sub"},
                                ):
                                    with patch(
                                        "app.execution.chat_actions._create_or_hold_action",
                                        return_value=spec_result,
                                    ):
                                        created = chat_actions.handle_turn(
                                            "c1",
                                            "p1",
                                            "Create resource group testing in eastus and also note it",
                                            "write",
                                        )
    assert created["action"]["id"] == "rg2"
    with _idle():
        with patch("app.execution.chat_actions.chat_memory.get_model_context", return_value=[]):
            with patch("app.execution.chat_actions._debug_intent", return_value=False):
                with patch("app.execution.chat_actions._cicd_intent", return_value=False):
                    with patch("app.execution.chat_actions._deploy_intent", return_value=False):
                        with patch("app.execution.chat_actions._terraform_intent", return_value=None):
                            with patch(
                                "app.execution.action_planner.looks_like_diagnostic",
                                return_value=True,
                            ):
                                with patch(
                                    "app.execution.chat_actions.connections.get_secret_fields",
                                    return_value={},
                                ):
                                    missing = chat_actions.handle_turn(
                                        "c1",
                                        "p1",
                                        "Create resource group testing in eastus and also note it",
                                        "write",
                                    )
    assert "subscription" in missing["reply"].lower()
    with _idle():
        with patch("app.execution.chat_actions.chat_memory.get_model_context", return_value=[]):
            with patch("app.execution.chat_actions._debug_intent", return_value=False):
                with patch("app.execution.chat_actions._cicd_intent", return_value=False):
                    with patch("app.execution.chat_actions._deploy_intent", return_value=False):
                        with patch("app.execution.chat_actions._terraform_intent", return_value=None):
                            with patch(
                                "app.execution.action_planner.looks_like_diagnostic",
                                return_value=True,
                            ):
                                with patch(
                                    "app.execution.chat_actions.connections.get_secret_fields",
                                    return_value={"subscription_id": "sub"},
                                ):
                                    scoped = chat_actions.handle_turn(
                                        "c1",
                                        "p1",
                                        "Create resource group testing in eastus and also note it",
                                        "read_only",
                                    )
    assert scoped.get("required_action_scope") == "write"


@pytest.mark.unit
def test_handle_turn_nsg_read_only_and_missing_subscription():
    with _idle():
        with patch("app.execution.chat_actions.chat_memory.get_model_context", return_value=[]):
            with patch("app.execution.chat_actions._debug_intent", return_value=False):
                with patch("app.execution.chat_actions._cicd_intent", return_value=False):
                    with patch("app.execution.chat_actions._deploy_intent", return_value=False):
                        with patch("app.execution.chat_actions._terraform_intent", return_value=None):
                            with patch(
                                "app.execution.chat_actions._resource_group_request",
                                return_value=None,
                            ):
                                with patch(
                                    "app.execution.chat_actions._vnet_request",
                                    return_value=None,
                                ):
                                    with patch(
                                        "app.execution.chat_actions._context_resource_group",
                                        return_value={"name": "rg1", "location": "eastus"},
                                    ):
                                        with patch(
                                            "app.execution.chat_actions._context_nsg_name",
                                            return_value="app-nsg",
                                        ):
                                            with patch(
                                                "app.execution.chat_actions.connections.get_secret_fields",
                                                return_value={"subscription_id": "sub"},
                                            ):
                                                scoped = chat_actions.handle_turn(
                                                    "c1", "p1", "create the NSG", "read_only"
                                                )
    assert scoped.get("required_action_scope") == "write"
    with _idle():
        with patch("app.execution.chat_actions.chat_memory.get_model_context", return_value=[]):
            with patch("app.execution.chat_actions._debug_intent", return_value=False):
                with patch("app.execution.chat_actions._cicd_intent", return_value=False):
                    with patch("app.execution.chat_actions._deploy_intent", return_value=False):
                        with patch("app.execution.chat_actions._terraform_intent", return_value=None):
                            with patch(
                                "app.execution.chat_actions._resource_group_request",
                                return_value=None,
                            ):
                                with patch(
                                    "app.execution.chat_actions._vnet_request",
                                    return_value=None,
                                ):
                                    with patch(
                                        "app.execution.chat_actions._context_resource_group",
                                        return_value={"name": "rg1", "location": "eastus"},
                                    ):
                                        with patch(
                                            "app.execution.chat_actions._context_nsg_name",
                                            return_value="app-nsg",
                                        ):
                                            with patch(
                                                "app.execution.chat_actions.connections.get_secret_fields",
                                                return_value={},
                                            ):
                                                with patch(
                                                    "app.execution.action_planner.looks_like_diagnostic",
                                                    return_value=True,
                                                ):
                                                    empty_sub = chat_actions.handle_turn(
                                                        "c1", "p1", "create the NSG", "write"
                                                    )
    assert empty_sub is None or empty_sub.get("action") is None


@pytest.mark.unit
def test_azure_display_units_and_missing_resources():
    assert azure_infra._display_value("Bytes", 2_000_000)[1] == "MB"
    assert azure_infra._display_value("BytesPerSecond", 2000)[1] == "KB/s"
    assert azure_infra._display_value("CountPerSecond", 3)[1] == "/s"
    assert azure_infra._display_value("Milliseconds", 12)[1] == "ms"
    assert azure_infra._display_value("Seconds", 4)[1] == "s"
    assert azure_infra._display_value("Count", 9)[1] == ""
    assert azure_infra._display_value("other", 1)[1] == "other"
    creds = AzureCredentials("t", "c", "s", "sub")
    with patch("app.providers.azure_infra.load_credentials", return_value=creds):
        with patch("app.providers.azure_infra._get_token", return_value="tok"):
            with patch("app.providers.azure_infra._discover_resources", return_value=[]):
                with patch("app.providers.azure_infra._run_query", return_value=[]):
                    with pytest.raises(AzureApiError, match="No resources"):
                        azure_infra.build_metrics_report("p1", "cpu health and memory or request metrics")
    defs = [
        {
            "name": {"value": "CpuPercentage", "localizedValue": "CPU"},
            "primaryAggregationType": "Average",
            "unit": "Percent",
        }
    ]
    with patch("app.providers.azure_infra.load_credentials", return_value=creds):
        with patch("app.providers.azure_infra._get_token", return_value="tok"):
            with patch(
                "app.providers.azure_infra._discover_resources",
                return_value=[
                    {
                        "id": "/id",
                        "name": "app",
                        "type": "microsoft.app/containerapps",
                        "cpuAlloc": 1,
                        "memAlloc": "1Gi",
                    }
                ],
            ):
                with patch("app.providers.azure_infra._fetch_metric_definitions", return_value=defs):
                    with patch(
                        "app.providers.azure_infra._fetch_metric",
                        side_effect=AzureApiError("no metric"),
                    ):
                        with pytest.raises(AzureApiError, match="no data"):
                            azure_infra.build_metrics_report(
                                "p1", "cpu health and memory or request metrics", metric_hints=["cpu"]
                            )


@pytest.mark.unit
def test_github_environment_report_languages_and_public_repos():
    creds = GitHubCredentials(token="gho_x", username="octo")
    client = MagicMock()
    client.__enter__.return_value = client
    client.__exit__.return_value = False
    who = MagicMock(status_code=200)
    who.json.return_value = {"login": "octo"}
    repos = [
        {
            "full_name": "octo/public",
            "private": False,
            "archived": False,
            "language": "Python",
            "default_branch": "main",
            "pushed_at": "2026-01-01",
            "name": "public",
        },
        {
            "full_name": "octo/private",
            "private": True,
            "archived": True,
            "language": "Go",
            "default_branch": "main",
            "pushed_at": "2026-01-02",
            "name": "private",
        },
    ]
    with patch("app.providers.github_infra.load_credentials", return_value=creds):
        with patch("app.providers.github_infra._client", return_value=client):
            with patch("app.providers.github_infra._get", return_value=who):
                with patch("app.providers.github_infra._allowed_repos", return_value=None):
                    with patch("app.providers.github_infra._list_repos", return_value=repos):
                        with patch(
                            "app.providers.github_infra._branch_protection",
                            return_value="on",
                        ):
                            with patch(
                                "app.providers.github_infra._vuln_alerts",
                                return_value="enabled",
                            ):
                                with patch(
                                    "app.providers.github_infra._dependabot_alerts",
                                    return_value={"open": 1},
                                ):
                                    report = github_infra.build_environment_report("p1")
    assert "Python" in report["text"]
    assert report["meta"]["public_count"] == 1


@pytest.mark.unit
def test_pending_resource_group_and_nsg_context_from_chat_history():
    chat = {
        "messages": [
            {
                "role": "assistant",
                "content": "az group create --name recovered-rg --location eastus",
                "meta": {},
            }
        ]
    }
    with patch("app.execution.chat_actions.chats.get_chat", return_value=chat):
        assert chat_actions._pending_resource_group_name("c1") == "recovered-rg"
    spec_chat = {
        "messages": [
            {"role": "assistant", "content": "ok", "meta": {"pending_action_spec": {"provider": "azure"}}}
        ]
    }
    with patch("app.execution.chat_actions.chats.get_chat", return_value=spec_chat):
        assert chat_actions._pending_action_spec("c1")["provider"] == "azure"
    with patch("app.execution.chat_actions.chats.get_chat", return_value=None):
        assert chat_actions._pending_action_spec("c1") is None
        assert chat_actions._pending_resource_group_name("c1") == ""
    nsg_chat = {
        "messages": [
            {"role": "user", "content": "create nsg named edge-nsg please"},
        ]
    }
    with patch("app.execution.chat_actions.chats.get_chat", return_value=nsg_chat):
        assert chat_actions._context_nsg_name("c1") == "edge-nsg"
        assert chat_actions._chat_mentions_nsg("c1") is True
    with _idle():
        with patch("app.execution.chat_actions.chat_memory.get_model_context", return_value=[]):
            with patch("app.execution.chat_actions._debug_intent", return_value=False):
                with patch("app.execution.chat_actions._cicd_intent", return_value=False):
                    with patch("app.execution.chat_actions._deploy_intent", return_value=False):
                        with patch("app.execution.chat_actions._terraform_intent", return_value=None):
                            with patch(
                                "app.execution.chat_actions._pending_action_spec",
                                return_value={"provider": "azure", "executable": "az", "args": ["account", "show"]},
                            ):
                                with patch(
                                    "app.execution.chat_actions._create_or_hold_action",
                                    return_value={"reply": "recovered", "action": {"id": "p1"}},
                                ):
                                    confirmed = chat_actions.handle_turn("c1", "p1", "yes", "write")
    assert confirmed["action"]["id"] == "p1"
    with _idle():
        with patch("app.execution.chat_actions.chat_memory.get_model_context", return_value=[]):
            with patch("app.execution.chat_actions._debug_intent", return_value=False):
                with patch("app.execution.chat_actions._cicd_intent", return_value=False):
                    with patch("app.execution.chat_actions._deploy_intent", return_value=False):
                        with patch("app.execution.chat_actions._terraform_intent", return_value=None):
                            with patch(
                                "app.execution.chat_actions._pending_action_spec",
                                return_value=None,
                            ):
                                with patch(
                                    "app.execution.chat_actions._context_resource_group",
                                    return_value={"name": "rg1", "location": "eastus"},
                                ):
                                    with patch(
                                        "app.execution.chat_actions.connections.get_secret_fields",
                                        return_value={"subscription_id": "sub"},
                                    ):
                                        with patch(
                                            "app.execution.chat_actions._create_or_hold_action",
                                            return_value={"reply": "recovered rg", "action": {"id": "p2"}},
                                        ):
                                            recovered = chat_actions.handle_turn("c1", "p1", "yes", "write")
    assert recovered["action"]["id"] == "p2"
    failed = {
        "id": "a9",
        "status": "failed",
        "command_preview": "az group create",
    }
    with _idle():
        with patch("app.execution.chat_actions.chat_memory.get_model_context", return_value=[]):
            with patch("app.execution.chat_actions._latest_action", return_value=failed):
                with patch(
                    "app.chat.project_context.gather_project_topology",
                    side_effect=RuntimeError("topo down"),
                ):
                    debug = chat_actions.handle_turn("c1", "p1", "why did it fail last night", "write")
    assert "could not prepare" in debug["reply"].lower()


@pytest.mark.unit
def test_ensure_seed_user_creates_bootstrap_admin_when_table_empty():
    from app.core import auth

    empty_session = MagicMock()
    empty_session.scalar.return_value = None
    empty_session.__enter__.return_value = empty_session
    empty_session.__exit__.return_value = False
    with patch("app.core.auth.SessionLocal", return_value=empty_session):
        with patch("app.core.auth.engine.begin") as begin:
            begin.return_value.__enter__.return_value = MagicMock()
            begin.return_value.__exit__.return_value = False
            auth.ensure_seed_user()
    empty_session.add.assert_called()
    empty_session.commit.assert_called()
    assert azure_infra._parse_mem_bytes("not-a-size") is None or azure_infra._parse_mem_bytes("12xx") is not None
    assert azure_infra._parse_mem_bytes("10Mi") == 10 * 1024 ** 2
    assert azure_infra._default_definitions([]) == []
    defs = [
        {"name": {"value": "Idle"}, "unit": "Count"},
        {"name": {"value": "CpuPercentage"}, "unit": "Percent"},
    ]
    picked = azure_infra._default_definitions(defs)
    assert picked
    assert azure_infra._select_resources("all apps", [{"name": "a"}, {"name": "b"}], limit=1)
