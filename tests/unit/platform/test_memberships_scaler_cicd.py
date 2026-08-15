"""Membership helpers, scaler stub, CI/CD disconnect, debug loop guards."""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException

from app.execution import cicd, debug_loop
from app.org_executors.scaler import LocalDockerScaler, get_scaler, local_container_name
from app.providers import aws_infra, azure_infra, github_infra
from app.tenancy import memberships


@pytest.mark.unit
def test_is_super_admin():
    assert memberships.is_super_admin({"role": "super_admin"})
    assert memberships.is_super_admin({"role": "admin"})
    assert not memberships.is_super_admin({"role": "org_admin"})
    assert not memberships.is_super_admin({})


@pytest.mark.unit
def test_assert_project_access_super_admin_bypasses():
    memberships.assert_project_access({"role": "super_admin", "id": "x"}, "any")


@pytest.mark.unit
def test_github_azure_aws_disconnected_without_secrets():
    with patch("app.providers.github_infra.connections.get_secret_fields", return_value=None):
        assert github_infra.is_connected("p1") is False
        with pytest.raises(github_infra.GitHubConnectionError):
            github_infra.load_credentials("p1")
    with patch("app.providers.azure_infra.connections.get_secret_fields", return_value=None):
        assert azure_infra.is_connected("p1") is False
        with pytest.raises(azure_infra.AzureConnectionError):
            azure_infra.load_credentials("p1")
    with patch("app.providers.aws_infra.connections.get_secret_fields", return_value=None):
        assert aws_infra.is_connected("p1") is False
        with pytest.raises(aws_infra.AwsConnectionError):
            aws_infra.load_credentials("p1")
    with patch(
        "app.providers.aws_infra.connections.get_secret_fields",
        return_value={"access_key_id": "ak"},
    ):
        with pytest.raises(aws_infra.AwsConnectionError, match="missing"):
            aws_infra.load_credentials("p1")


@pytest.mark.unit
def test_github_filter_repos_and_error_detail():
    repos = [{"full_name": "acme/app"}, {"full_name": "other/x"}]
    filtered = github_infra._filter_repos(repos, {"acme/app"})
    assert filtered == [{"full_name": "acme/app"}]
    assert github_infra._filter_repos(repos, None) == repos
    resp = MagicMock()
    resp.json.return_value = {"message": "Bad credentials"}
    resp.text = "nope"
    assert "Bad credentials" in github_infra._error_detail(resp)
    resp.json.side_effect = ValueError
    resp.text = "plain"
    assert github_infra._error_detail(resp) == "plain"


@pytest.mark.unit
def test_local_scaler_without_docker(monkeypatch):
    monkeypatch.setattr("app.org_executors.scaler._docker_available", lambda: False)
    names = LocalDockerScaler().scale_org("org-123", min_replicas=1, max_replicas=2)
    assert set(names) == {"azure", "aws", "github"}
    assert "azure" in local_container_name("org-123", "azure")
    scaler = get_scaler()
    assert scaler is not None


@pytest.mark.unit
def test_watch_github_returns_empty_when_disconnected():
    with patch("app.execution.cicd.github_infra.is_connected", return_value=False):
        assert cicd.watch_github_workflow_runs("p1") == []
    with patch("app.execution.cicd.github_infra.is_connected", return_value=True):
        with patch("app.execution.cicd.projects.get_repos", return_value=[]):
            assert cicd.watch_github_workflow_runs("p1") == []


@pytest.mark.unit
def test_failed_runs_flattens_failures():
    with patch(
        "app.execution.cicd.watch_github_workflow_runs",
        return_value=[
            {
                "repo": "acme/app",
                "runs": [
                    {"id": 1, "conclusion": "success"},
                    {"id": 2, "conclusion": "failure", "name": "ci"},
                ],
            }
        ],
    ):
        failed = cicd.failed_runs("p1")
    assert len(failed) == 1
    assert failed[0]["id"] == 2


@pytest.mark.unit
def test_propose_fix_rejects_non_failed_actions():
    with patch(
        "app.execution.debug_loop.service.get_action",
        return_value={"id": "a1", "status": "succeeded"},
    ):
        with pytest.raises(ValueError, match="failed"):
            debug_loop.propose_fix("a1")


@pytest.mark.unit
def test_propose_fix_parses_model_json():
    completion = SimpleNamespace(
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(
                    content='{"root_cause":"auth","fix_summary":"retry","retry_safe":true,"modified_args":["account","show"]}'
                )
            )
        ]
    )
    with patch(
        "app.execution.debug_loop.service.get_action",
        return_value={"id": "a1", "status": "failed", "result": {"stdout": "", "stderr": "boom"}},
    ):
        with patch("app.execution.debug_loop.azure_client.chat", return_value=completion):
            proposal = debug_loop.propose_fix("a1")
    assert proposal["retry_safe"] is True
    assert proposal["modified_args"] == ["account", "show"]
    assert proposal["root_cause"] == "auth"
