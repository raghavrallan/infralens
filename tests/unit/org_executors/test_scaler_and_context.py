"""Org executor scaler backends and project context inventory helpers."""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from app.chat.project_context import (
    _extract_iac_inventory,
    _infer_app_structure,
    _kind_for_path,
    _live_resource_summary,
    build_fresh_context,
    gather_project_topology,
)
from app.org_executors.scaler import (
    AzureContainerAppsScaler,
    LocalDockerScaler,
    apply_scale,
    get_scaler,
    scaler_kind,
)
from app.providers.azure_infra import AzureApiError
from app.providers.github_infra import GitHubApiError


@pytest.mark.unit
def test_local_scaler_starts_existing_containers():
    with patch("app.org_executors.scaler._docker_available", return_value=True):
        with patch(
            "app.org_executors.scaler._container_exists",
            side_effect=lambda name: name.endswith("azure-exec-org123456789"),
        ):
            with patch("app.org_executors.scaler._run") as run:
                names = LocalDockerScaler().scale_org(
                    "org-1234567890", min_replicas=1, max_replicas=1
                )
    assert "azure" in names
    run.assert_called()
    with patch("app.org_executors.scaler._docker_available", return_value=True):
        with patch("app.org_executors.scaler._container_exists", return_value=False):
            names = LocalDockerScaler().scale_org("org-1", min_replicas=0, max_replicas=1)
    assert set(names) >= {"azure", "aws", "github"}


@pytest.mark.unit
def test_aca_scaler_create_and_scale(monkeypatch):
    monkeypatch.setenv("ACA_RESOURCE_GROUP", "rg")
    monkeypatch.setenv("ACA_ENVIRONMENT", "env")
    monkeypatch.setenv("AZURE_SUBSCRIPTION_ID", "sub")
    monkeypatch.setenv("ORG_EXECUTOR_SCALE_BACKEND", "aca")
    scaler = AzureContainerAppsScaler()
    with patch("app.org_executors.scaler.shutil.which", return_value="/usr/bin/az"):
        assert scaler.enabled() is True
        with patch.object(scaler, "_app_exists", return_value=False):
            with patch.object(scaler, "_create_app") as create:
                with patch.object(scaler, "_set_scale") as scale:
                    names = scaler.scale_org("org-1", min_replicas=0, max_replicas=2)
        assert create.call_count == 3
        assert scale.call_count == 3
        assert names["azure"]
    with patch("app.org_executors.scaler.shutil.which", return_value="/usr/bin/az"):
        assert scaler_kind() == "aca"
        with patch.object(AzureContainerAppsScaler, "scale_org", return_value={"azure": "app"}):
            applied = apply_scale("org-1", min_replicas=0, max_replicas=1)
        assert applied["azure"] == "app"
    monkeypatch.setenv("ORG_EXECUTOR_SCALE_BACKEND", "local")
    assert isinstance(get_scaler(), LocalDockerScaler)
    with patch("app.org_executors.scaler.shutil.which", return_value=None):
        with pytest.raises(RuntimeError, match="ACA_RESOURCE_GROUP"):
            AzureContainerAppsScaler().scale_org("org-1", min_replicas=0, max_replicas=1)


@pytest.mark.unit
def test_aca_helpers_and_run_errors():
    scaler = AzureContainerAppsScaler()
    scaler.resource_group = "rg"
    scaler.subscription = "sub"
    scaler.environment = "env"
    with patch(
        "app.org_executors.scaler._run",
        return_value=SimpleNamespace(returncode=0, stdout="id"),
    ):
        assert scaler._app_exists("app") is True
    with patch("app.org_executors.scaler._run") as run:
        scaler._set_scale("app", 0, 1)
        run.assert_called()
    with patch("app.org_executors.scaler._run") as run:
        scaler._create_app("org-1", "azure", "app")
        assert run.call_args[0][0][1] == "containerapp"
    with patch(
        "app.org_executors.scaler.subprocess.run",
        side_effect=FileNotFoundError("docker"),
    ):
        with pytest.raises(RuntimeError, match="not found"):
            from app.org_executors.scaler import _run

            _run(["docker", "ps"], check=False)


@pytest.mark.unit
def test_kind_for_path_and_app_structure():
    assert _kind_for_path("infra/main.tf") == "terraform"
    assert _kind_for_path("main.bicep") == "bicep"
    assert _kind_for_path("Dockerfile") == "dockerfile"
    assert _kind_for_path(".github/workflows/ci.yml") == "pipeline"
    assert _kind_for_path("charts/helm/values") == "kubernetes"
    assert _kind_for_path("notes.md") == "other"
    structure = _infer_app_structure(
        [{"kind": "terraform"}, {"kind": "pipeline"}],
        ["acme/api", "acme/web", "acme/infra"],
    )
    assert structure["has_terraform"] is True
    assert structure["backend_repos"] == ["acme/api"]


@pytest.mark.unit
def test_extract_iac_inventory_parses_code_report():
    with patch("app.chat.project_context.github_infra.is_connected", return_value=False):
        assert _extract_iac_inventory("p1") == []
    text = "### acme/app — infra/main.tf (branch: main)\n```hcl\nresource x\n```"
    with patch("app.chat.project_context.github_infra.is_connected", return_value=True):
        with patch(
            "app.chat.project_context.github_infra.build_code_report",
            return_value={"text": text, "meta": {}},
        ):
            files = _extract_iac_inventory("p1")
    assert files[0]["path"] == "infra/main.tf"
    with patch("app.chat.project_context.github_infra.is_connected", return_value=True):
        with patch(
            "app.chat.project_context.github_infra.build_code_report",
            side_effect=GitHubApiError("denied"),
        ):
            assert _extract_iac_inventory("p1") == []
    with patch("app.chat.project_context.github_infra.is_connected", return_value=True):
        with patch(
            "app.chat.project_context.github_infra.build_code_report",
            return_value={"text": "", "meta": {"files": 3}},
        ):
            mixed = _extract_iac_inventory("p1")
    assert mixed[0]["kind"] == "mixed"


@pytest.mark.unit
def test_live_resource_summary_and_topology_error():
    with patch("app.chat.project_context.azure_infra.is_connected", return_value=True):
        with patch("app.chat.project_context.aws_infra.is_connected", return_value=True):
            with patch("app.chat.project_context.github_infra.is_connected", return_value=True):
                with patch(
                    "app.chat.project_context.azure_infra.discover_topology",
                    return_value={
                        "subscription": "sub",
                        "resource_count": 2,
                        "resource_groups": ["rg"],
                        "relationships": [1],
                    },
                ):
                    with patch(
                        "app.chat.project_context.aws_infra.discover_topology",
                        return_value={"account": "1", "region": "us-east-1", "resource_count": 1, "relationships": []},
                    ):
                        with patch(
                            "app.chat.project_context.github_infra.build_environment_report",
                            return_value={"meta": {"login": "octo", "repos": 1}},
                        ):
                            summary = _live_resource_summary("p1")
    assert summary["azure"]["resource_count"] == 2
    assert summary["aws"]["account"] == "1"
    assert summary["github"]["login"] == "octo"
    with patch("app.chat.project_context.azure_infra.is_connected", return_value=True):
        with patch("app.chat.project_context.aws_infra.is_connected", return_value=False):
            with patch("app.chat.project_context.github_infra.is_connected", return_value=False):
                with patch(
                    "app.chat.project_context.azure_infra.discover_topology",
                    side_effect=AzureApiError("denied"),
                ):
                    err = _live_resource_summary("p1")
    assert "error" in err["azure"]
    with patch(
        "app.chat.project_context.build_project_context",
        side_effect=RuntimeError("boom"),
    ):
        text = gather_project_topology("p1")
    assert "unavailable" in text.lower()
    with patch("app.chat.project_context.projects.get_project", return_value={"name": "Demo", "repos": []}):
        with patch(
            "app.chat.project_context.connections.all_status",
            return_value=[
                {"provider": "azure", "connected": True, "identity": "sub"},
                {"provider": "github", "connected": True, "identity": "octo"},
            ],
        ):
            ctx = build_fresh_context("p1", user_messages=["need an API"], docs="build a platform")
    prompt = ctx.to_prompt_text()
    assert "PROJECT TOPOLOGY" in prompt
    assert "Default Azure scope" in prompt
