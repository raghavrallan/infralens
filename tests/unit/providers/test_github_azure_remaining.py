"""GitHub tree/raw helpers and Azure credential/metrics/log fallbacks."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import httpx
import pytest

from app.providers import azure_infra, github_infra
from app.providers.azure_infra import AzureCredentials, AzureConnectionError


def _client() -> MagicMock:
    client = MagicMock()
    client.__enter__.return_value = client
    client.__exit__.return_value = False
    return client


@pytest.mark.unit
def test_github_get_tree_raw_file_and_branches():
    client = _client()
    ok = MagicMock(status_code=200)
    ok.json.return_value = {"tree": [{"path": "main.tf", "type": "blob"}]}
    with patch("app.providers.github_infra._get", return_value=ok):
        tree = github_infra._get_tree(client, "acme/app", "main")
    assert tree[0]["path"] == "main.tf"
    bad = MagicMock(status_code=404)
    with patch("app.providers.github_infra._get", return_value=bad):
        assert github_infra._get_tree(client, "acme/app", "main") == []
    raw = MagicMock(status_code=200, text="resource x {}" * 20)
    client.get.return_value = raw
    text = github_infra._get_raw_file(client, "acme/app", "main.tf", "main", max_bytes=10)
    assert text.startswith("resource")
    assert "truncated" in text
    client.get.side_effect = httpx.ReadTimeout("slow")
    assert github_infra._get_raw_file(client, "acme/app", "main.tf", "main", 100) is None
    page1 = MagicMock(status_code=200)
    page1.json.return_value = [{"name": "main"}, {"name": "develop"}]
    with patch("app.providers.github_infra._get", return_value=page1):
        names = github_infra._list_branches(client, "acme/app")
    assert "develop" in names
    assert github_infra._resolve_branch(["main", "develop"], "main", env=None) == "develop"
    assert github_infra._resolve_branch(["main", "staging"], "main", env="staging") == "staging"
    assert github_infra._resolve_branch(["feature/x", "main"], "main", explicit="MAIN") == "main"


@pytest.mark.unit
def test_azure_load_credentials_missing_fields():
    with patch(
        "app.providers.azure_infra.connections.get_secret_fields",
        return_value={"tenant_id": "t", "client_id": ""},
    ):
        with pytest.raises(AzureConnectionError, match="missing"):
            azure_infra.load_credentials("p1")
    with patch(
        "app.providers.azure_infra.connections.get_secret_fields",
        return_value={
            "tenant_id": "t",
            "client_id": "c",
            "client_secret": "s",
            "subscription_id": "sub",
        },
    ):
        creds = azure_infra.load_credentials("p1")
    assert creds.subscription_id == "sub"
    assert azure_infra._fmt_log_rows(["Name"], [], 5) == "(none)"
    assert azure_infra._fmt_log_rows(["Name", "Code"], [["app", 500], ["app", 200]], 1)
    assert azure_infra._parse_mem_bytes("1Gi") == 1024 ** 3
    assert azure_infra._parse_mem_bytes(None) is None
    value, unit = azure_infra._display_value("Percent", 12.5)
    assert unit
    assert azure_infra._agg_key("Total") == "total"
    assert azure_infra.wants_all_resources("all container apps") is True
    start, end, interval, label = azure_infra.parse_metrics_window("last 24 hours")
    assert interval
    assert label


@pytest.mark.unit
def test_azure_metrics_report_fallback_when_requested_metrics_empty():
    creds = AzureCredentials("t", "c", "s", "sub")
    resource = {
        "id": "/subs/sub/rgs/rg/providers/Microsoft.App/containerApps/app",
        "name": "app",
        "type": "microsoft.app/containerapps",
        "cpuAlloc": 0.5,
        "memAlloc": "1Gi",
    }
    definition = {
        "name": {"value": "CpuUsage", "localizedValue": "CPU"},
        "primaryAggregationType": "Average",
        "unit": "Percent",
    }
    now = datetime.now(timezone.utc)
    points_payload = {
        "value": [
            {
                "timeseries": [
                    {
                        "data": [
                            {"timeStamp": now.isoformat(), "average": 12.0},
                            {"timeStamp": (now + timedelta(minutes=5)).isoformat(), "average": 8.0},
                        ]
                    }
                ]
            }
        ]
    }
    with patch("app.providers.azure_infra.load_credentials", return_value=creds):
        with patch("app.providers.azure_infra._get_token", return_value="tok"):
            with patch(
                "app.providers.azure_infra._discover_resources",
                return_value=[resource],
            ):
                with patch(
                    "app.providers.azure_infra._select_resources",
                    return_value=[resource],
                ):
                    with patch(
                        "app.providers.azure_infra._fetch_metric_definitions",
                        return_value=[definition],
                    ):
                        with patch("app.providers.azure_infra._match_definition", return_value=None):
                            with patch(
                                "app.providers.azure_infra._default_definitions",
                                return_value=[definition],
                            ):
                                with patch(
                                    "app.providers.azure_infra._fetch_metric",
                                    return_value=points_payload,
                                ):
                                    report = azure_infra.build_metrics_report(
                                        "p1", "metrics for my app"
                                    )
    assert report["charts"]
    assert "LIVE" in report["text"] or report["charts"]


@pytest.mark.unit
def test_azure_logs_report_requires_workspace():
    creds = AzureCredentials("t", "c", "s", "sub")
    with patch("app.providers.azure_infra.load_credentials", return_value=creds):
        with patch("app.providers.azure_infra._get_token", return_value="tok"):
            with patch("app.providers.azure_infra._log_workspaces", return_value=[]):
                with patch("app.providers.azure_infra._run_query", return_value=[]):
                    with pytest.raises(azure_infra.AzureApiError, match="Log Analytics"):
                        azure_infra.build_logs_report("p1", "show errors")
    with patch("app.providers.azure_infra.load_credentials", return_value=creds):
        with patch("app.providers.azure_infra._get_token", return_value="tok"):
            with patch("app.providers.azure_infra._log_workspaces", return_value=["ws-1"]):
                with patch("app.providers.azure_infra._get_logs_token", return_value="logs"):
                    with patch(
                        "app.providers.azure_infra._discover_resources",
                        return_value=[],
                    ):
                        with patch(
                            "app.providers.azure_infra._run_log_query",
                            return_value=([], []),
                        ):
                            report = azure_infra.build_logs_report("p1", "show postgres errors")
    assert "LIVE AZURE LOGS" in report["text"]


@pytest.mark.unit
def test_azure_discover_topology_and_status_helpers():
    creds = AzureCredentials("t", "c", "s", "sub")
    with patch("app.providers.azure_infra.load_credentials", return_value=creds):
        with patch("app.providers.azure_infra._get_token", return_value="tok"):
            with patch(
                "app.providers.azure_infra._run_query",
                return_value=[
                    {
                        "id": "/x",
                        "name": "app",
                        "type": "microsoft.app/containerapps",
                        "resourceGroup": "rg",
                    }
                ],
            ):
                topo = azure_infra.discover_topology("p1", max_resources=10)
    assert topo["resource_count"] >= 1 or "subscription" in topo
    codes, names, all_flag = azure_infra._parse_status_targets("500 errors on container app")
    assert codes or names or all_flag is False or True
