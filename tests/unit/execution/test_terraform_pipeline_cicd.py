"""Terraform pipeline, CI/CD watchers, debug retry, and deploy failure hook."""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from app.execution import cicd, debug_loop, terraform_runner
from app.execution.deploy_orchestrator import handle_failed_deploy, json_safe_summary, run_deploy_pipeline


@pytest.mark.unit
def test_run_local_phase_rejects_unknown_and_missing_binary(tmp_path, monkeypatch):
    monkeypatch.setattr("app.execution.terraform_runner._WORKSPACE_ROOT", tmp_path)
    with pytest.raises(ValueError, match="Unsupported"):
        terraform_runner.run_local_phase("p1", "fmt")
    with patch("app.execution.terraform_runner._terraform_available", return_value=False):
        with pytest.raises(RuntimeError, match="not installed"):
            terraform_runner.run_local_phase("p1", "plan")
    completed = SimpleNamespace(returncode=0, stdout="Plan: 1 to add, 0 to change, 0 to destroy.", stderr="")
    with patch("app.execution.terraform_runner._terraform_available", return_value=True):
        with patch("app.execution.terraform_runner.subprocess.run", return_value=completed):
            result = terraform_runner.run_local_phase("p1", "plan")
    assert result["plan_summary"]["add"] == 1


@pytest.mark.unit
def test_create_terraform_action_and_pipeline_without_binary(tmp_path, monkeypatch):
    monkeypatch.setattr("app.execution.terraform_runner._WORKSPACE_ROOT", tmp_path)
    fake = {"id": "tf1", "status": "awaiting_approval", "command_preview": "terraform apply"}
    with patch("app.execution.terraform_runner.service.create_action", return_value=fake):
        with patch(
            "app.execution.terraform_runner.connections.get_secret_fields",
            return_value={"tenant_id": "t"},
        ):
            action = terraform_runner.create_terraform_action(
                project_id="p1", phase="apply", plan_summary={"add": 1, "change": 0, "destroy": 0}
            )
    assert action["id"] == "tf1"
    with pytest.raises(ValueError):
        terraform_runner.create_terraform_action(project_id="p1", phase="fmt")
    destroy = terraform_runner.build_rollback_operation("destroy", "default")
    assert destroy["args"][0] == "apply"
    apply_rb = terraform_runner.build_rollback_operation("apply", "default", {"destroy": 2})
    assert "-destroy" in apply_rb["args"]
    with patch("app.execution.terraform_runner._terraform_available", return_value=False):
        with patch(
            "app.execution.terraform_runner.create_terraform_action",
            return_value=fake,
        ):
            pipeline = terraform_runner.pipeline("p1", run_local_plan=False)
    assert pipeline["ok"] is True
    assert pipeline["action"]["id"] == "tf1"
    markdown = "```hcl file=main.tf\nresource \"null_resource\" \"x\" {}\n```"
    prepared = terraform_runner.prepare_from_skill_output("p1", markdown)
    assert "main.tf" in prepared["files"]
    with pytest.raises(ValueError, match="No Terraform"):
        terraform_runner.prepare_from_skill_output("p1", "no fences")


@pytest.mark.unit
def test_cloud_provider_for_project():
    with patch(
        "app.execution.terraform_runner.connections.get_secret_fields",
        side_effect=lambda _pid, provider: {"k": "v"} if provider == "aws" else None,
    ):
        assert terraform_runner._cloud_provider_for_project("p1") == "aws"
    with patch(
        "app.execution.terraform_runner.connections.get_secret_fields",
        return_value=None,
    ):
        assert terraform_runner._cloud_provider_for_project("p1") == "azure"


@pytest.mark.unit
def test_cicd_watch_create_retry_and_hooks():
    client = MagicMock()
    client.__enter__.return_value = client
    client.__exit__.return_value = False
    resp = MagicMock(status_code=200, content=b"{}")
    resp.json.return_value = {
        "workflow_runs": [
            {"id": 1, "name": "ci", "status": "completed", "conclusion": "failure", "html_url": "http://x"}
        ]
    }
    with patch("app.execution.cicd.github_infra.is_connected", return_value=True):
        with patch("app.execution.cicd.projects.get_repos", return_value=["acme/app"]):
            with patch("app.execution.cicd.github_infra.load_credentials", return_value=MagicMock()):
                with patch("app.execution.cicd.github_infra._client", return_value=client):
                    with patch("app.execution.cicd.github_infra._get", return_value=resp):
                        runs = cicd.watch_github_workflow_runs("p1")
    assert runs[0]["repo"] == "acme/app"
    err = MagicMock(status_code=403, content=b"nope")
    with patch("app.execution.cicd.github_infra.is_connected", return_value=True):
        with patch("app.execution.cicd.projects.get_repos", return_value=["acme/app"]):
            with patch("app.execution.cicd.github_infra.load_credentials", return_value=MagicMock()):
                with patch("app.execution.cicd.github_infra._client", return_value=client):
                    with patch("app.execution.cicd.github_infra._get", return_value=err):
                        with patch(
                            "app.execution.cicd.github_infra._error_detail",
                            return_value="denied",
                        ):
                            failed = cicd.watch_github_workflow_runs("p1")
    assert failed[0]["error"] == "denied"
    with patch("app.execution.cicd.service.create_action", return_value={"id": "r1"}):
        action = cicd.create_rerun_action("p1", "acme/app", 9)
    assert action["id"] == "r1"
    with patch(
        "app.execution.cicd.service.get_action",
        return_value={"id": "a1", "status": "succeeded"},
    ):
        waited = cicd.wait_for_action("a1", timeout=0.01, poll=0.001)
    assert waited["status"] == "succeeded"
    with patch(
        "app.execution.cicd.failed_runs",
        return_value=[{"repo": "acme/app", "id": 2}],
    ):
        with patch("app.execution.cicd.create_rerun_action", side_effect=RuntimeError("no gh")):
            with patch(
                "app.org_executors.settings.resolve_org_id_for_project",
                return_value="org",
            ):
                with patch("app.execution.cicd.queue.queue_snapshot", return_value={"depth": 0}):
                    prepared = cicd.auto_retry_failed_builds("p1")
    assert prepared["prepared"][0]["error"]
    with patch(
        "app.execution.cicd.watch_github_workflow_runs",
        return_value=[{"runs": [{"status": "completed", "conclusion": "success"}]}],
    ):
        with patch(
            "app.execution.deploy_orchestrator.run_deploy_pipeline",
            return_value={"ok": True},
        ):
            hook = cicd.after_success_deploy_hook("p1")
    assert hook["ok"] is True
    with patch("app.execution.debug_loop.run_debug_cycle", return_value={"ok": True}):
        assert cicd.debug_failed_run("p1", "a1")["ok"] is True


@pytest.mark.unit
def test_debug_retry_and_cycle(monkeypatch):
    monkeypatch.setattr("app.execution.debug_loop.time.sleep", lambda *_a, **_k: None)
    original = {
        "id": "a1",
        "status": "failed",
        "project_id": "p1",
        "provider": "azure",
        "target": "rg/demo",
        "access_scope": "write",
        "operation": {
            "executable": "az",
            "args": ["group", "create", "--name", "demo"],
            "rollback": "az group delete",
            "preflight": [],
            "verify": ["group", "show"],
        },
    }
    proposal = {
        "retry_safe": True,
        "modified_args": ["group", "create", "--name", "demo"],
        "fix_summary": "retry",
        "root_cause": "auth",
        "original": {
            "provider": "azure",
            "executable": "az",
            "args": ["group", "create", "--name", "demo"],
            "target": "rg/demo",
            "access_scope": "write",
        },
    }
    with patch("app.execution.debug_loop.service.get_action", return_value=original):
        with patch("app.execution.debug_loop.service.create_action", return_value={"id": "r1"}):
            retry = debug_loop.create_retry_action("a1", proposal)
    assert retry["id"] == "r1"
    with pytest.raises(ValueError, match="not retry-safe"):
        debug_loop.create_retry_action("a1", {"retry_safe": False})
    with patch("app.execution.debug_loop.propose_fix", return_value=proposal):
        with patch("app.execution.debug_loop.create_retry_action", return_value={"id": "r1"}):
            with patch("app.execution.debug_loop.chat_memory.get_memory", return_value={}):
                with patch("app.execution.debug_loop.chat_memory.record_deployment_outcome"):
                    cycle = debug_loop.run_debug_cycle("a1", chat_id="c1")
    assert cycle["ok"] is True
    unsafe = {**proposal, "retry_safe": False}
    with patch("app.execution.debug_loop.propose_fix", return_value=unsafe):
        blocked = debug_loop.run_debug_cycle("a1")
    assert blocked["ok"] is False


@pytest.mark.unit
def test_run_deploy_pipeline_and_failed_hook():
    fake_pipeline = {
        "ok": True,
        "phases": [{"phase": "init", "skipped": True}],
        "plan_summary": {"add": 1, "change": 0, "destroy": 0},
        "action": {"id": "d1", "status": "awaiting_approval", "command_preview": "terraform apply"},
    }
    with patch("app.execution.terraform_runner.pipeline", return_value=fake_pipeline):
        result = run_deploy_pipeline("p1", strategy="canary")
    assert result["plan"]["ok"] is True
    assert result["pipeline"]["action"]["id"] == "d1"
    assert "add" in json_safe_summary({"add": 1, "change": 0, "destroy": 0})
    with patch(
        "app.execution.deploy_orchestrator.service.get_action",
        return_value={"id": "a1", "status": "failed", "rollback_operation": {"args": ["destroy"]}},
    ):
        with patch(
            "app.execution.debug_loop.run_debug_cycle",
            return_value={"ok": True},
        ):
            failed = handle_failed_deploy("a1")
    assert failed["auto_rollback_recommended"] is True
