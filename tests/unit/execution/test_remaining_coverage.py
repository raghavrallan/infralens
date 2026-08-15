"""Remaining high-coverage tests: actions, chat, scaler helpers, auth, runner, architect explore."""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

import app.skills  # noqa: F401 — break circular import before architect graph
from app.agents.solution_architect import graph
from app.agents.solution_architect.state import empty_state
from app.core import auth
from app.execution import chat_actions
from app.intelligence import scheduler as intel_scheduler
from app.intelligence import worker as intel_worker
from app.platform import oauth_providers
from executors.common.runner import CliResult, run_cli


@pytest.mark.unit
def test_handle_turn_nsg_and_delete_resource_group():
    with patch("app.execution.chat_actions._pending_action", return_value=None):
        with patch("app.execution.chat_actions._latest_action", return_value=None):
            with patch("app.execution.chat_actions.chat_memory.get_model_context", return_value=[]):
                with patch(
                    "app.execution.chat_actions._context_resource_group",
                    return_value={"name": "rg1", "location": "eastus"},
                ):
                    with patch("app.execution.chat_actions._context_nsg_name", return_value=""):
                        nsg = chat_actions.handle_turn(
                            "c1", "p1", "create an nsg in that resource group", "write"
                        )
    assert nsg["required_action_scope"] == "write"
    with patch("app.execution.chat_actions._pending_action", return_value=None):
        with patch("app.execution.chat_actions._latest_action", return_value=None):
            with patch("app.execution.chat_actions.chat_memory.get_model_context", return_value=[]):
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
                                return_value={"reply": "delete prepared", "action": {"id": "d1"}},
                            ):
                                deleted = chat_actions.handle_turn(
                                    "c1", "p1", "please delete the resource group", "write"
                                )
    assert deleted["action"]["id"] == "d1"


@pytest.mark.unit
def test_handle_turn_yes_recovers_pending_spec():
    spec = chat_actions._resource_group_spec("demo", "eastus", "sub")
    with patch("app.execution.chat_actions._pending_action", return_value=None):
        with patch("app.execution.chat_actions._latest_action", return_value=None):
            with patch("app.execution.chat_actions.chat_memory.get_model_context", return_value=[]):
                with patch("app.execution.chat_actions._pending_action_spec", return_value=spec):
                    with patch(
                        "app.execution.chat_actions._create_or_hold_action",
                        return_value={"reply": "recovered", "action": {"id": "a1"}},
                    ):
                        result = chat_actions.handle_turn("c1", "p1", "yes", "write")
    assert result["action"]["id"] == "a1"


@pytest.mark.unit
def test_azure_oauth_start_and_finish(monkeypatch):
    monkeypatch.setenv("AZURE_OAUTH_CLIENT_ID", "cid")
    monkeypatch.setenv("AZURE_OAUTH_CLIENT_SECRET", "secret")
    monkeypatch.setenv("AZURE_OAUTH_TENANT_ID", "tenant")
    started = oauth_providers.start_azure_oauth(project_id="p1", request_base="http://api.test/")
    assert "login.microsoftonline.com" in started["authorize_url"]
    token_resp = MagicMock()
    token_resp.raise_for_status.return_value = None
    token_resp.json.return_value = {"access_token": "aztok"}
    client = MagicMock()
    client.__enter__.return_value = client
    client.__exit__.return_value = False
    client.post.return_value = token_resp
    with patch("app.platform.oauth_providers.httpx.Client", return_value=client):
        with patch(
            "app.platform.oauth_providers.connections.set_connection",
            return_value={"provider": "azure", "connected": True},
        ):
            finished = oauth_providers.finish_azure_oauth(
                code="abc", state=started["state"], request_base="http://api.test/"
            )
    assert finished["project_id"] == "p1"


@pytest.mark.unit
def test_scheduler_sync_and_enqueue_helpers():
    fake = MagicMock()
    intel_scheduler._scheduler = fake
    with patch("app.intelligence.scheduler._pause_workflows_without_cloud"):
        with patch(
            "app.intelligence.scheduler.store.scheduled_workflows",
            return_value=[{"id": "w1", "schedule_cron": "0 * * * *"}],
        ):
            intel_scheduler.sync_schedules()
    fake.add_job.assert_called()
    fake.remove_all_jobs.assert_called()
    with patch("app.intelligence.scheduler.store.create_run", return_value=None):
        intel_scheduler._enqueue_scheduled("w1")
    with patch("app.intelligence.scheduler.store.create_run", return_value={"id": "r1"}):
        with patch("app.intelligence.scheduler.enqueue_run", side_effect=RuntimeError("redis")):
            with patch("app.intelligence.scheduler.store.mark_run_failed") as failed:
                intel_scheduler._enqueue_scheduled("w1")
    failed.assert_called_once()
    intel_scheduler._scheduler = None


@pytest.mark.unit
def test_intelligence_worker_run_success_and_failure():
    workflow = {
        "id": "w1",
        "project_id": "p1",
        "objective": "review",
        "name": "Review",
        "environment": "dev",
        "module": "security_patch",
        "skills": ["cloud_posture", "missing"],
    }
    skill = MagicMock()
    skill.run.return_value = SimpleNamespace(content="- finding")
    with patch("app.intelligence.worker.init_db"):
        with patch("app.intelligence.worker.store.get_run", return_value={"id": "r1", "workflow_id": "w1"}):
            with patch("app.intelligence.worker.store.get_workflow", return_value=workflow):
                with patch("app.intelligence.worker.store.mark_run_running"):
                    with patch("app.intelligence.worker._gather_context", return_value="LIVE"):
                        with patch("app.intelligence.worker._usable_context", return_value="LIVE"):
                            with patch("app.intelligence.worker.registry.get", side_effect=lambda n: skill if n == "cloud_posture" else None):
                                with patch(
                                    "app.intelligence.worker.findings_mod.build_findings",
                                    return_value=[{"title": "open nsg"}],
                                ):
                                    with patch("app.intelligence.worker.store.save_findings", return_value=2):
                                        with patch("app.intelligence.worker.store.mark_run_succeeded"):
                                            result = intel_worker.run_workflow("r1")
        assert result["findings"] == 2
        with patch("app.intelligence.worker.store.get_run", return_value=None):
            assert intel_worker.run_workflow("missing")["findings"] == 0
        with patch("app.intelligence.worker.store.get_run", return_value={"id": "r1", "workflow_id": "w1"}):
            with patch("app.intelligence.worker.store.get_workflow", return_value=workflow):
                with patch("app.intelligence.worker.store.mark_run_running"):
                    with patch("app.intelligence.worker._gather_context", side_effect=RuntimeError("down")):
                        with patch("app.intelligence.worker.store.mark_run_failed") as failed:
                            result = intel_worker.run_workflow("r1")
        assert result["findings"] == 0
        failed.assert_called()


@pytest.mark.unit
def test_architect_explore_t2_and_design_fallback():
    state = empty_state(objective="Add PCI event bus", project_id="p1", tier="T2")
    with patch("app.agents.solution_architect.graph.tools.get_cloud_inventory", return_value="inventory"):
        with patch("app.agents.solution_architect.graph.tools.inventory_is_empty", return_value=False):
            with patch("app.agents.solution_architect.graph.tools.get_cost_report", return_value="cost"):
                with patch("app.agents.solution_architect.graph.tools.get_code_artifacts", return_value="code"):
                    with patch("app.agents.solution_architect.graph.tools.search_precedent", return_value=""):
                        with patch("app.agents.solution_architect.graph.tools.run_skill", return_value="skill"):
                            with patch(
                                "app.agents.solution_architect.graph._json_chat",
                                return_value={"mode": "brownfield", "tier": "T3", "notes": "explored"},
                            ):
                                explored = graph.explore(state, lambda _e: None)
    assert explored["mode"] == "brownfield"
    assert explored["tier"] == "T3"
    with patch("app.agents.solution_architect.graph._json_chat", return_value={}):
        with patch("app.agents.solution_architect.graph.tools.design_resource_plan", return_value="lld"):
            designed = graph.design(empty_state(objective="queue", tier="T2"), lambda _e: None)
    assert designed.get("candidates") is not None


@pytest.mark.unit
def test_run_cli_timeout_oserror_and_cancel_check():
    with patch("executors.common.runner._resolve_argv", return_value=["az", "account", "show"]):
        with patch(
            "executors.common.runner.subprocess.run",
            side_effect=__import__("subprocess").TimeoutExpired(cmd="az", timeout=1),
        ):
            timed = run_cli(["az", "account", "show"], {})
    assert timed.timed_out is True
    with patch("executors.common.runner._resolve_argv", side_effect=OSError("missing")):
        missing = run_cli(["az", "account", "show"], {})
    assert missing.returncode == -1
    proc = MagicMock()
    proc.communicate.return_value = ("ok", "")
    proc.returncode = 0
    with patch("executors.common.runner._resolve_argv", return_value=["az", "account", "show"]):
        with patch("executors.common.runner.subprocess.Popen", return_value=proc):
            result = run_cli(["az", "account", "show"], {}, cancel_check=lambda: False)
    assert result.returncode == 0
    proc2 = MagicMock()
    proc2.poll.return_value = None
    timeout_exc = __import__("subprocess").TimeoutExpired(cmd="az", timeout=0.5)

    def _communicate(timeout=None):
        if timeout is not None:
            raise timeout_exc
        return ("", "")

    proc2.communicate.side_effect = _communicate
    proc2.kill.return_value = None
    with patch("executors.common.runner._resolve_argv", return_value=["az", "account", "show"]):
        with patch("executors.common.runner.subprocess.Popen", return_value=proc2):
            canceled = run_cli(["az", "account", "show"], {}, timeout=1, cancel_check=lambda: True)
    assert canceled.canceled is True


@pytest.mark.unit
def test_hash_password_and_authenticate_invalid(monkeypatch):
    hashed = auth.hash_password("secret12")
    assert hashed != "secret12"
    assert auth.verify_password("secret12", hashed) is True
    assert auth.verify_password("wrong", hashed) is False
    with patch("app.core.auth.SessionLocal") as session_local:
        session = MagicMock()
        session.scalar.return_value = None
        session_local.return_value.__enter__.return_value = session
        session_local.return_value.__exit__.return_value = False
        assert auth.authenticate("nobody", "x") is None
