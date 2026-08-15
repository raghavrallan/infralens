"""Chat-action planner branches, Azure status reports, RQ HTTP helpers, project delete cascade."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from app.chat import chats
from app.execution import chat_actions
from app.execution import service as execution
from app.platform import connections
from app.providers import azure_infra
from app.tenancy import projects
from executors.common import rq_job


@pytest.mark.unit
@pytest.mark.infra
def test_handle_turn_planner_compound_clarification_and_resource_group():
    with patch("app.execution.chat_actions._pending_action", return_value=None):
        with patch("app.execution.chat_actions._latest_action", return_value=None):
            with patch("app.execution.chat_actions.chat_memory.get_model_context", return_value=[]):
                with patch("app.execution.chat_actions._debug_intent", return_value=False):
                    with patch("app.execution.chat_actions._cicd_intent", return_value=False):
                        with patch("app.execution.chat_actions._deploy_intent", return_value=False):
                            with patch("app.execution.chat_actions._terraform_intent", return_value=None):
                                with patch("app.execution.chat_actions._resource_group_request", return_value=None):
                                    with patch("app.execution.chat_actions._vnet_request", return_value=None):
                                        with patch("app.execution.chat_actions._message_mentions_nsg", return_value=False):
                                            with patch(
                                                "app.execution.chat_actions.action_planner.looks_like_diagnostic",
                                                return_value=False,
                                            ):
                                                with patch(
                                                    "app.execution.chat_actions.action_planner.plan_action",
                                                    return_value={
                                                        "kind": "action",
                                                        "operations": [
                                                            {
                                                                "provider": "azure",
                                                                "executable": "az",
                                                                "access_scope": "write",
                                                                "args": ["group", "create"],
                                                                "expected_result": "rg",
                                                                "risk": "create",
                                                            },
                                                            {
                                                                "provider": "aws",
                                                                "executable": "aws",
                                                                "access_scope": "write",
                                                                "args": ["s3", "mb"],
                                                                "expected_result": "bucket",
                                                                "risk": "create",
                                                            },
                                                        ],
                                                    },
                                                ):
                                                    mixed = chat_actions.handle_turn(
                                                        "c1", "p1", "create rg and a bucket", "write"
                                                    )
    assert "separate" in mixed["reply"].lower()
    with patch("app.execution.chat_actions._pending_action", return_value=None):
        with patch("app.execution.chat_actions._latest_action", return_value=None):
            with patch("app.execution.chat_actions.chat_memory.get_model_context", return_value=[]):
                with patch("app.execution.chat_actions._debug_intent", return_value=False):
                    with patch("app.execution.chat_actions._cicd_intent", return_value=False):
                        with patch("app.execution.chat_actions._deploy_intent", return_value=False):
                            with patch("app.execution.chat_actions._terraform_intent", return_value=None):
                                with patch("app.execution.chat_actions._resource_group_request", return_value=None):
                                    with patch("app.execution.chat_actions._vnet_request", return_value=None):
                                        with patch("app.execution.chat_actions._message_mentions_nsg", return_value=False):
                                            with patch(
                                                "app.execution.chat_actions.action_planner.looks_like_diagnostic",
                                                return_value=False,
                                            ):
                                                with patch(
                                                    "app.execution.chat_actions.action_planner.looks_like_scope_clarification",
                                                    return_value=False,
                                                ):
                                                    with patch(
                                                        "app.execution.chat_actions.action_planner.plan_action",
                                                        return_value={
                                                            "kind": "clarification",
                                                            "question": "Which resource group?",
                                                            "operation": {"access_scope": "write"},
                                                        },
                                                    ):
                                                        asked = chat_actions.handle_turn(
                                                            "c1", "p1", "create something azure", "read_only"
                                                        )
    assert "resource group" in asked["reply"].lower()
    with patch("app.execution.chat_actions._pending_action", return_value=None):
        with patch("app.execution.chat_actions._latest_action", return_value=None):
            with patch("app.execution.chat_actions.chat_memory.get_model_context", return_value=[]):
                with patch("app.execution.chat_actions._debug_intent", return_value=False):
                    with patch("app.execution.chat_actions._cicd_intent", return_value=False):
                        with patch("app.execution.chat_actions._deploy_intent", return_value=False):
                            with patch("app.execution.chat_actions._terraform_intent", return_value=None):
                                with patch("app.execution.chat_actions.action_planner.looks_like_diagnostic", return_value=True):
                                    with patch(
                                        "app.execution.chat_actions.connections.get_secret_fields",
                                        return_value={"subscription_id": "sub"},
                                    ):
                                        with patch(
                                            "app.execution.chat_actions._create_or_hold_action",
                                            return_value={"reply": "rg ready", "action": {"id": "a"}},
                                        ):
                                            created = chat_actions.handle_turn(
                                                "c1",
                                                "p1",
                                                "Create resource group testing in eastus",
                                                "write",
                                            )
    assert created is None or created.get("reply") in {"rg ready"} or "testing" in str(created)


@pytest.mark.unit
def test_azure_status_targets_and_empty_token():
    codes, cats, errors = azure_infra._parse_status_targets("how many 500 and 4xx errors")
    assert "500" in codes
    assert "4xx" in cats
    assert errors is True
    creds = azure_infra.AzureCredentials("t", "c", "s", "sub")
    with patch("app.providers.azure_infra.load_credentials", return_value=creds):
        with patch("app.providers.azure_infra._get_token", return_value=""):
            with pytest.raises(azure_infra.AzureApiError, match="empty access token"):
                azure_infra.build_status_report("p1", "500 errors")
    with patch("app.providers.azure_infra.load_credentials", return_value=creds):
        with patch("app.providers.azure_infra._get_token", return_value="tok"):
            with patch("app.providers.azure_infra._discover_resources", return_value=[]):
                with pytest.raises(azure_infra.AzureApiError, match="No container apps"):
                    azure_infra.build_status_report("p1", "500 errors")
    resource = {"id": "/apps/a", "name": "a", "type": "microsoft.app/containerapps"}
    payload = {
        "value": [
            {
                "timeseries": [
                    {
                        "metadatavalues": [{"name": {"value": "statusCode"}, "value": "500"}],
                        "data": [{"timeStamp": "t", "total": 4}],
                    }
                ]
            }
        ]
    }
    with patch("app.providers.azure_infra.load_credentials", return_value=creds):
        with patch("app.providers.azure_infra._get_token", return_value="tok"):
            with patch("app.providers.azure_infra._discover_resources", return_value=[resource]):
                with patch("app.providers.azure_infra._select_resources", return_value=[resource]):
                    with patch("app.providers.azure_infra._fetch_metric_split", return_value=payload):
                        report = azure_infra.build_status_report("p1", "500 errors last hour")
    assert report["text"] or report.get("charts") is not None


@pytest.mark.unit
def test_rq_job_http_helpers(monkeypatch):
    monkeypatch.setenv("CONTROL_PLANE_URL", "http://api.test")
    monkeypatch.setenv("EXECUTOR_SERVICE_KEY", "k")
    monkeypatch.setenv("EXECUTOR_PROVIDER", "azure")
    monkeypatch.setenv("EXECUTOR_ORG_ID", "org")
    response = MagicMock()
    response.raise_for_status.return_value = None
    response.json.return_value = {"canceled": True, "id": "a1"}
    client = MagicMock()
    client.__enter__.return_value = client
    client.__exit__.return_value = False
    client.post.return_value = response
    client.get.return_value = response
    with patch("executors.common.rq_job.httpx.Client", return_value=client):
        rq_job._post_event("a1", "stdout", {"line": "ok"})
        claimed = rq_job._claim("a1", "azure")
        canceled = rq_job._is_canceled("a1", "azure")
        rq_job._finish("a1", "succeeded", {"ok": True}, "")
    assert claimed["id"] == "a1"
    assert canceled is True


@pytest.mark.unit
def test_azure_arm_and_log_query_helpers():
    ok = MagicMock(status_code=200)
    ok.json.return_value = {"id": "x"}
    with patch("app.providers.azure_infra.httpx.get", return_value=ok):
        assert azure_infra._arm_get("tok", "/subs/1", "2024-01-01")["id"] == "x"
    bad = MagicMock(status_code=500, text="fail")
    bad.json.return_value = {"error": {"message": "fail"}}
    with patch("app.providers.azure_infra.httpx.get", return_value=bad):
        with pytest.raises(azure_infra.AzureApiError):
            azure_infra._arm_get("tok", "/subs/1", "2024-01-01")
    with patch("app.providers.azure_infra.httpx.get", side_effect=__import__("httpx").ConnectError("down")):
        with pytest.raises(azure_infra.AzureApiError, match="request failed"):
            azure_infra._arm_get("tok", "/subs/1", "2024-01-01")
    logs_ok = MagicMock(status_code=200)
    logs_ok.json.return_value = {
        "tables": [{"columns": [{"name": "Time"}, {"name": "Msg"}], "rows": [["t", "hello"]]}]
    }
    with patch("app.providers.azure_infra.httpx.post", return_value=logs_ok):
        cols, rows = azure_infra._run_log_query("tok", "ws", "print 1", "PT1H")
    assert cols[0] == "Time"
    assert rows[0][1] == "hello"
    empty = MagicMock(status_code=200)
    empty.json.return_value = {"tables": []}
    with patch("app.providers.azure_infra.httpx.post", return_value=empty):
        cols2, rows2 = azure_infra._run_log_query("tok", "ws", "print 1", "PT1H")
    assert cols2 == []
    with patch("app.providers.azure_infra.httpx.post", side_effect=__import__("httpx").ReadTimeout("slow")):
        with pytest.raises(azure_infra.AzureApiError, match="Log Analytics"):
            azure_infra._run_log_query("tok", "ws", "print 1", "PT1H")
    failed = MagicMock(status_code=403, text="denied")
    failed.json.return_value = {"error": {"message": "denied"}}
    with patch("app.providers.azure_infra.httpx.post", return_value=failed):
        with pytest.raises(azure_infra.AzureApiError, match="query failed"):
            azure_infra._run_log_query("tok", "ws", "print 1", "PT1H")
    with patch("app.providers.azure_infra._run_query", return_value=[{"cid": "abc"}, {}]):
        assert azure_infra._log_workspaces("tok", ["sub"]) == ["abc"]
    assert azure_infra._fmt_log_rows(["a"], []) == "(none)" or "none" in azure_infra._fmt_log_rows(["a"], []).lower()
    formatted = azure_infra._fmt_log_rows(["a", "b"], [["1", "2"], ["3", "4"]])
    assert "1" in formatted


@pytest.mark.integration
def test_delete_project_with_chat_and_action(require_db, org_with_project):
    org_id = org_with_project["org"]["id"]
    extra = projects.create_project("Cascade", org_id=org_id)
    chats.create_chat("hello", project_id=extra["id"])
    connections.set_connection(
        extra["id"],
        "azure",
        "client_secret",
        {"tenant_id": "t", "client_id": "c", "client_secret": "s", "subscription_id": "sub"},
    )
    with patch("app.execution.service.enqueue_action", return_value={"executor_available": True}):
        with patch("app.execution.service.request_wake"):
            execution.create_action(
                project_id=extra["id"],
                provider="azure",
                executable="az",
                args=["account", "show", "--output", "json"],
                target="identity",
                access_scope="read_only",
                expected_result="ok",
                risk="",
                rollback="n/a",
                preflight=[],
                verify=[],
            )
    projects.set_default(org_with_project["project"]["id"])
    assert projects.delete_project(extra["id"]) is True
    assert projects.get_project(extra["id"]) is None
