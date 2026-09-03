"""Isolated workspace, GitHub mapping, and gated apply."""
from __future__ import annotations

from unittest.mock import patch

import pytest

from app.platform.engineering import iac_delivery, iac_workspace
from app.providers import github_git


@pytest.mark.unit
def test_sync_pins_local_backend_for_isolated_plan(tmp_path, monkeypatch):
    monkeypatch.setattr("app.execution.terraform_runner._WORKSPACE_ROOT", tmp_path)
    with patch(
        "app.platform.engineering.iac_workspace.load_generated_files",
        return_value={
            "providers.tf": "terraform {}",
            "backend.tf": 'terraform {\n  backend "azurerm" {}\n}\n',
        },
    ):
        result = iac_workspace.sync("p1", "9b234cd8-10be-4ba0-982b-0cec9af1b033")
    backend = (tmp_path / "p1" / result["workspace_name"] / "backend.tf").read_text(encoding="utf-8")
    assert 'backend "local"' in backend
    assert "terraform.tfstate" in backend
    assert "azurerm" not in backend
    assert result["backend"] == "local"


@pytest.mark.unit
def test_workspace_name_and_cloud_env_are_project_scoped(monkeypatch):
    assert iac_workspace.workspace_name("4fbe5b38-4ab1-4a0b-9e20-42c1379f6819").startswith("4fbe5b38")
    assert iac_workspace.workspace_name("../x") == "default"
    monkeypatch.setenv("ARM_CLIENT_SECRET", "host-secret")
    monkeypatch.setenv("PATH", "/usr/bin")
    with patch(
        "app.platform.engineering.iac_workspace.connections.get_secret_fields",
        side_effect=lambda project_id, provider: (
            {"client_id": "cid", "client_secret": "proj-secret", "tenant_id": "tid", "subscription_id": "sub"}
            if provider == "azure" and project_id == "default"
            else None
        ),
    ):
        env = iac_workspace.project_cloud_env("default")
        other = iac_workspace.project_cloud_env("other")
    assert env["ARM_CLIENT_SECRET"] == "proj-secret"
    assert env["ARM_SUBSCRIPTION_ID"] == "sub"
    assert "ARM_CLIENT_SECRET" not in other
    assert other.get("PATH")


@pytest.mark.unit
def test_github_push_stays_on_mapped_repo_and_safe_paths():
    with patch("app.providers.github_git.projects.get_repos", return_value=["acme/app", "acme/infra"]):
        assert github_git.mapped_repo("p1") == "acme/infra"
        github_git.assert_mapped("p1", "acme/infra")
        with pytest.raises(ValueError, match="outside"):
            github_git.assert_mapped("p1", "acme/other")
        with pytest.raises(ValueError, match="[Uu]nsafe"):
            github_git.push_files_pr("p1", {"../escape.tf": "x"}, branch="x", title="t")


@pytest.mark.unit
def test_plan_requires_passed_init():
    with patch(
        "app.platform.engineering.iac_delivery._run",
        return_value={"id": "r1", "project_id": "p1", "artifacts": {}},
    ):
        with pytest.raises(ValueError, match="init"):
            iac_delivery.run_plan("r1")


@pytest.mark.unit
def test_init_repair_retries_and_keeps_prior_turns():
    prior = {
        "turns": [
            {
                "phase": "init",
                "attempt": 1,
                "diagnosis": "earlier provider pin",
                "files": ["providers.tf"],
                "error": "missing provider",
            }
        ]
    }
    inits = iter(
        [
            {
                "ok": False,
                "phase": "init",
                "error": "Backend initialization required",
                "synced": {"workspace": "/tmp"},
                "terraform_init": {"status": "failed"},
            },
            {
                "ok": True,
                "phase": "init",
                "error": "",
                "synced": {"workspace": "/tmp"},
                "terraform_init": {"status": "passed", "returncode": 0},
            },
        ]
    )

    def fake_patch(_run_id, updates):
        return {"id": "r1", "artifacts": updates}

    with patch(
        "app.platform.engineering.iac_delivery._run",
        return_value={"id": "r1", "project_id": "p1", "artifacts": {"terraform_repair": prior}},
    ):
        with patch("app.platform.engineering.iac_delivery._patch", side_effect=fake_patch):
            with patch("app.platform.engineering.iac_delivery._run_init_once", side_effect=lambda *_a, **_k: next(inits)):
                with patch(
                    "app.platform.engineering.iac_delivery._repair_once",
                    return_value={
                        "ok": True,
                        "stop": False,
                        "diagnosis": "use local backend",
                        "files": ["backend.tf"],
                        "repair": {
                            "turns": prior["turns"]
                            + [{"phase": "init", "attempt": 1, "diagnosis": "use local backend", "files": ["backend.tf"]}]
                        },
                    },
                ):
                    result = iac_delivery.run_init("r1")
    turns = result["artifacts"]["terraform_repair"]["turns"]
    assert result["artifacts"]["terraform_init"]["status"] == "passed"
    assert any(item.get("diagnosis") == "earlier provider pin" for item in turns)
    assert any(item.get("files") == ["backend.tf"] for item in turns)


@pytest.mark.unit
def test_parse_already_exists_extracts_address_and_id():
    error = (
        'Error: a resource with the ID '
        '"/subscriptions/sub/resourceGroups/rg-infralens-prod/providers/Microsoft.Cache/redis/redis-infralens" '
        "already exists - to be managed via Terraform this resource needs to be imported into the State.\n\n"
        "  with azurerm_redis_cache.app,\n"
        "  on cache.tf line 1,\n"
    )
    found = iac_delivery.parse_already_exists(error)
    assert found == [
        (
            "azurerm_redis_cache.app",
            "/subscriptions/sub/resourceGroups/rg-infralens-prod/providers/Microsoft.Cache/redis/redis-infralens",
        )
    ]


@pytest.mark.unit
def test_apply_requires_lead_and_passed_plan():
    with pytest.raises(PermissionError):
        iac_delivery.run_apply("r1", user_role="developer")
    with patch(
        "app.platform.engineering.iac_delivery._run",
        return_value={"id": "r1", "project_id": "p1", "artifacts": {"action_diff": {"status": "failed"}}},
    ):
        with pytest.raises(ValueError, match="plan"):
            iac_delivery.run_apply("r1", user_role="devops_lead")
    with patch(
        "app.platform.engineering.iac_delivery._run",
        return_value={
            "id": "r1",
            "project_id": "p1",
            "artifacts": {"action_diff": {"status": "passed", "destroy": 2}},
        },
    ):
        with pytest.raises(ValueError, match="destroy"):
            iac_delivery.run_apply("r1", user_role="super_admin", confirm_destroy=False)


@pytest.mark.unit
def test_github_push_files_pr_uses_project_token(monkeypatch):
    class Resp:
        def __init__(self, code, payload):
            self.status_code = code
            self._payload = payload

        def json(self):
            return self._payload

    class Client:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def post(self, path, json=None):
            if path.endswith("/git/trees"):
                return Resp(201, {"sha": "tree1"})
            if path.endswith("/git/commits"):
                return Resp(201, {"sha": "commit1"})
            if path.endswith("/git/refs"):
                return Resp(201, {})
            if path.endswith("/pulls"):
                return Resp(201, {"html_url": "https://github.com/acme/app/pull/9", "number": 9})
            return Resp(400, {"message": path})

        def patch(self, path, json=None):
            return Resp(200, {})

    def fake_get(client, path, params=None):
        if path.endswith("/repos/acme/app"):
            return Resp(200, {"default_branch": "master"})
        if "git/ref/heads" in path:
            return Resp(200, {"object": {"sha": "base1"}})
        if "git/commits" in path:
            return Resp(200, {"tree": {"sha": "oldtree"}})
        if path.endswith("/pulls"):
            return Resp(200, [])
        return Resp(404, {})

    with patch("app.providers.github_git.projects.get_repos", return_value=["acme/app"]):
        with patch("app.providers.github_infra.load_credentials", return_value=object()):
            with patch("app.providers.github_infra._client", return_value=Client()):
                with patch("app.providers.github_infra._get", side_effect=fake_get):
                    result = github_git.push_files_pr(
                        "p1",
                        {"providers.tf": "terraform {}"},
                        branch="infralens/iac/p1/run1",
                        title="infra: test",
                    )
    assert result["repo"] == "acme/app"
    assert result["pr_url"].endswith("/pull/9")
    assert result["files"][0].startswith("infra/infralens/")
