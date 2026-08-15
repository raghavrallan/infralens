"""GitHub helper branches and Azure log/metrics HTTP helpers."""
from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import httpx
import pytest

from app.providers import azure_infra, github_infra
from app.providers.azure_infra import AzureCredentials
from app.providers.github_infra import GitHubCredentials


@pytest.mark.unit
def test_github_protection_vuln_and_dependabot_status_codes():
    client = MagicMock()
    mapping = {
        200: "protected",
        404: "not protected",
        403: "unknown (token lacks admin scope)",
        500: "unknown (500)",
    }
    for status, expected in mapping.items():
        resp = MagicMock(status_code=status)
        with patch("app.providers.github_infra._get", return_value=resp):
            assert github_infra._branch_protection(client, "o/r", "main") == expected
    vuln = {204: "enabled", 404: "disabled", 401: "unknown (token lacks scope)", 418: "unknown (418)"}
    for status, expected in vuln.items():
        resp = MagicMock(status_code=status)
        with patch("app.providers.github_infra._get", return_value=resp):
            assert github_infra._vuln_alerts(client, "o/r") == expected
    alerts = MagicMock(status_code=200)
    alerts.json.return_value = [
        {
            "state": "open",
            "severity": "high",
            "dependency": {"package": {"name": "leftpad", "ecosystem": "npm"}, "manifest_path": "pkg.json"},
            "security_advisory": {"severity": "high", "cve_id": "CVE-1"},
        }
    ]
    with patch("app.providers.github_infra._get", return_value=alerts):
        result = github_infra._dependabot_alerts(client, "o/r")
    assert result["status"] == "available"
    assert result["alerts"]


@pytest.mark.unit
def test_github_list_repos_pagination_and_get_http_error():
    creds = GitHubCredentials(token="gho_x", org="acme")
    client = MagicMock()
    page1 = MagicMock(status_code=200)
    page1.json.return_value = [{"full_name": "acme/one"}] * 100
    page2 = MagicMock(status_code=200)
    page2.json.return_value = [{"full_name": "acme/two"}]
    client.get.side_effect = [page1, page2]
    repos = github_infra._list_repos(client, creds)
    assert any(r["full_name"] == "acme/one" for r in repos)
    client.get.side_effect = httpx.ConnectError("down")
    with pytest.raises(github_infra.GitHubApiError):
        github_infra._get(client, "/user")


@pytest.mark.unit
def test_github_resolve_branch_and_list_picker():
    branches = ["develop", "main", "feature"]
    assert github_infra._resolve_branch(branches, "main", env="dev", explicit=None) in branches
    assert github_infra._resolve_branch(branches, "main", env=None, explicit="feature") == "feature"
    creds = GitHubCredentials(token="gho_x")
    client = MagicMock()
    client.__enter__.return_value = client
    client.__exit__.return_value = False
    who = MagicMock(status_code=200)
    who.json.return_value = {"login": "octo"}
    with patch("app.providers.github_infra.load_credentials", return_value=creds):
        with patch("app.providers.github_infra._client", return_value=client):
            with patch("app.providers.github_infra._get", return_value=who):
                with patch(
                    "app.providers.github_infra._list_repos",
                    return_value=[{"full_name": "octo/app", "private": True, "default_branch": "main"}],
                ):
                    rows = github_infra.list_repos_for_picker("p1")
    assert rows[0]["full_name"] == "octo/app"


@pytest.mark.unit
def test_azure_logs_report_with_workspace_and_apps():
    creds = AzureCredentials("t", "c", "s", "sub")
    app = {
        "name": "app1",
        "id": "/subscriptions/s/resourceGroups/rg/providers/Microsoft.App/containerApps/app1",
        "type": "microsoft.app/containerapps",
    }
    props = {
        "properties": {"provisioningState": "Succeeded", "runningStatus": "Running"},
        "value": [
            {
                "name": "app1--abc",
                "properties": {
                    "createdTime": "2026-08-01",
                    "active": True,
                    "healthState": "Healthy",
                    "provisioningState": "Succeeded",
                    "runningState": "Running",
                    "replicas": 1,
                    "trafficWeight": 100,
                    "template": {"containers": [{"image": "img:1"}]},
                },
            }
        ],
    }
    log_resp = MagicMock(status_code=200)
    log_resp.json.return_value = {
        "tables": [{"columns": [{"name": "TimeGenerated"}, {"name": "Log_s"}], "rows": [["t", "boom"]]}]
    }
    with patch("app.providers.azure_infra.load_credentials", return_value=creds):
        with patch("app.providers.azure_infra._get_token", return_value="tok"):
            with patch("app.providers.azure_infra._log_workspaces", return_value=["ws-1"]):
                with patch("app.providers.azure_infra._get_logs_token", return_value="logs"):
                    with patch("app.providers.azure_infra._discover_resources", return_value=[app]):
                        with patch("app.providers.azure_infra._arm_get", return_value=props):
                            with patch("app.providers.azure_infra.httpx.post", return_value=log_resp):
                                report = azure_infra.build_logs_report("p1", "show errors last hour", resource_name="app1")
    assert "LIVE AZURE LOGS" in report["text"] or "app1" in report["text"]


@pytest.mark.unit
def test_azure_discover_resources_and_metric_split_success():
    ok = MagicMock(status_code=200)
    ok.json.return_value = {"data": [{"name": "app1", "id": "/id", "type": "microsoft.app/containerapps"}]}
    with patch("app.providers.azure_infra.httpx.post", return_value=ok):
        rows = azure_infra._discover_resources("tok", ["sub"], ["microsoft.app/containerapps"], "app1")
    assert rows
    metric = MagicMock(status_code=200)
    metric.json.return_value = {"value": []}
    with patch("app.providers.azure_infra.httpx.get", return_value=metric):
        payload = azure_infra._fetch_metric_split(
            "tok",
            "/id",
            "Requests",
            "Total",
            datetime(2026, 8, 15, tzinfo=timezone.utc),
            datetime(2026, 8, 15, 1, tzinfo=timezone.utc),
            "PT1H",
            "statusCode",
        )
    assert "value" in payload
    assert azure_infra._default_definitions(
        [{"name": {"value": "CpuPercentage"}, "isDimensionRequired": False, "primaryAggregationType": "Average"}]
    )
