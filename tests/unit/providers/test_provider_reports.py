"""Exercise Azure/AWS/GitHub report builders with mocked I/O."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from app.providers import aws_infra, azure_infra, github_infra
from app.providers.azure_infra import AzureCredentials
from app.providers.github_infra import GitHubCredentials


@pytest.mark.unit
def test_azure_build_environment_report_and_empty_token():
    creds = AzureCredentials("t", "c", "s", "sub-1")
    inventory = [{"name": "rg1", "type": "microsoft.resources/resourcegroups"}]
    counts = [{"type": "microsoft.resources/resourcegroups", "total": 1}]
    with patch("app.providers.azure_infra.load_credentials", return_value=creds):
        with patch("app.providers.azure_infra._get_token", return_value="tok"):
            with patch(
                "app.providers.azure_infra._run_query",
                side_effect=lambda *_a, **_k: counts if "summarize" in _a[2] else inventory,
            ):
                report = azure_infra.build_environment_report("p1")
    assert "rg1" in report["text"]
    assert report["meta"]["subscription"] == "sub-1"
    with patch("app.providers.azure_infra.load_credentials", return_value=creds):
        with patch("app.providers.azure_infra._get_token", return_value=""):
            with pytest.raises(azure_infra.AzureApiError, match="empty access token"):
                azure_infra.build_environment_report("p1")


@pytest.mark.unit
def test_azure_discover_topology_builds_edges():
    creds = AzureCredentials("t", "c", "s", "sub-1")
    rows = [
        {
            "name": "app1",
            "type": "microsoft.web/sites",
            "resourceGroup": "rg1",
            "vnet": "/subscriptions/x/resourceGroups/rg1/providers/Microsoft.Network/virtualNetworks/vnet1",
            "subnet": "",
            "nsg": "null",
        }
    ]
    with patch("app.providers.azure_infra.load_credentials", return_value=creds):
        with patch("app.providers.azure_infra._get_token", return_value="tok"):
            with patch("app.providers.azure_infra._run_query", return_value=rows):
                topo = azure_infra.discover_topology("p1", max_resources=10)
    assert topo["provider"] == "azure"
    assert topo["resource_count"] == 1
    assert topo["relationships"]


@pytest.mark.unit
def test_azure_probe_error_is_captured():
    creds = AzureCredentials("t", "c", "s", None)
    calls = {"n": 0}

    def fake_query(_token, _subs, query):
        calls["n"] += 1
        if "summarize" in query or "project name, type" in query:
            return []
        raise azure_infra.AzureApiError("denied")

    with patch("app.providers.azure_infra.load_credentials", return_value=creds):
        with patch("app.providers.azure_infra._get_token", return_value="tok"):
            with patch("app.providers.azure_infra._run_query", side_effect=fake_query):
                report = azure_infra.build_environment_report("p1")
    assert "could not evaluate" in report["text"]


@pytest.mark.unit
def test_github_environment_report_success_and_auth_failure():
    creds = GitHubCredentials(token="gho_x", username="octo")
    who = MagicMock(status_code=200)
    who.json.return_value = {"login": "octo"}
    repos = [
        {
            "full_name": "octo/app",
            "private": False,
            "archived": False,
            "default_branch": "main",
            "language": "Python",
            "pushed_at": "2026-01-01",
            "name": "app",
        }
    ]
    client = MagicMock()
    client.__enter__.return_value = client
    client.__exit__.return_value = False
    with patch("app.providers.github_infra.load_credentials", return_value=creds):
        with patch("app.providers.github_infra._allowed_repos", return_value=None):
            with patch("app.providers.github_infra._client", return_value=client):
                with patch("app.providers.github_infra._get", return_value=who):
                    with patch("app.providers.github_infra._list_repos", return_value=repos):
                        with patch("app.providers.github_infra._branch_protection", return_value="on"):
                            with patch("app.providers.github_infra._vuln_alerts", return_value="enabled"):
                                with patch("app.providers.github_infra._dependabot_alerts", return_value="0"):
                                    report = github_infra.build_environment_report("p1")
    assert "octo/app" in report["text"]
    denied = MagicMock(status_code=401)
    denied.json.return_value = {"message": "Bad credentials"}
    denied.text = "nope"
    with patch("app.providers.github_infra.load_credentials", return_value=creds):
        with patch("app.providers.github_infra._allowed_repos", return_value=None):
            with patch("app.providers.github_infra._client", return_value=client):
                with patch("app.providers.github_infra._get", return_value=denied):
                    with pytest.raises(github_infra.GitHubApiError, match="rejected"):
                        github_infra.build_environment_report("p1")


@pytest.mark.unit
def test_aws_environment_report_with_stubbed_probes():
    creds = aws_infra.AwsCredentials("AKI", "SECRET", "us-east-1")
    session = MagicMock()
    with patch("app.providers.aws_infra.load_credentials", return_value=creds):
        with patch("app.providers.aws_infra._session", return_value=session):
            with patch(
                "app.providers.aws_infra._caller_identity",
                return_value={"Account": "1", "Arn": "arn:aws:iam::1:user/x"},
            ):
                with patch("app.providers.aws_infra._ec2_summary", return_value=([], [])):
                    with patch("app.providers.aws_infra._s3_summary", return_value=[]):
                        with patch("app.providers.aws_infra._rds_summary", return_value=[]):
                            with patch("app.providers.aws_infra._iam_summary", return_value={"users": 1}):
                                report = aws_infra.build_environment_report("p1")
    assert report["meta"]["account"] == "1"
    assert "IAM" in report["text"]
