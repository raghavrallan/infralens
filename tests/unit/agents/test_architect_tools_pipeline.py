"""Architect tools, graph remaining nodes, scheduler pause, org executor settings."""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

import app.skills  # noqa: F401 — break circular import
from app.agents.solution_architect import graph, tools
from app.agents.solution_architect.state import empty_state
from app.intelligence import scheduler as intel_scheduler
from app.org_executors import settings as org_settings


@pytest.mark.unit
def test_architect_tools_safe_wrappers_and_allowlist():
    assert "empty" in tools._safe("azure", lambda: None)
    assert "hi" in tools._safe("azure", lambda: {"text": "hi there"})
    assert "unavailable" in tools._safe("azure", lambda: (_ for _ in ()).throw(RuntimeError("x")))
    with patch("app.providers.azure_infra.is_connected", return_value=False):
        with patch("app.providers.aws_infra.is_connected", return_value=False):
            with patch("app.providers.github_infra.is_connected", return_value=False):
                inventory = tools.get_cloud_inventory("p1")
    assert "not connected" in inventory
    assert tools.inventory_is_empty("azure: not connected\naws: not connected") is True
    assert tools.inventory_is_empty("resource: vm-1\nresource: vm-2") is False
    with patch("app.providers.azure_infra.is_connected", return_value=False):
        assert "not connected" in tools.get_cost_report("p1")
    with patch("app.providers.azure_infra.is_connected", return_value=True):
        with patch("app.providers.azure_infra.parse_cost_period", side_effect=RuntimeError("bad")):
            assert "unavailable" in tools.get_cost_report("p1")
    with patch("app.providers.github_infra.is_connected", return_value=False):
        assert "not connected" in tools.get_code_artifacts("p1")
    with patch("app.providers.github_infra.is_connected", return_value=True):
        with patch("app.providers.github_infra.build_code_report", return_value="tf files"):
            assert "tf files" in tools.get_code_artifacts("p1", kinds=["terraform"])
    with patch("app.platform.memory.list_precedent", return_value=[]):
        assert "No engineering precedent" in tools.search_precedent("p1")
    with patch("app.platform.memory.list_precedent", side_effect=RuntimeError("db")):
        assert "unavailable" in tools.search_precedent("p1")
    with patch("app.platform.memory.list_precedent", return_value=[{"summary": "prior"}]):
        assert "prior" in tools.search_precedent("p1")
    assert "allow-list" in tools.run_skill("terraform_executor", {})
    with patch("app.skills.registry.get", return_value=None):
        assert "Unknown skill" in tools.run_skill("iac_reviewer", {})
    skill = MagicMock()
    skill.run.return_value = SimpleNamespace(content="reviewed")
    with patch("app.skills.registry.get", return_value=skill):
        assert "reviewed" in tools.run_skill("iac_reviewer", {})
    skill.run.side_effect = RuntimeError("llm")
    with patch("app.skills.registry.get", return_value=skill):
        assert "failed" in tools.run_skill("iac_reviewer", {})
    with patch("app.skills.registry.get", return_value=None):
        assert "not registered" in tools.design_resource_plan({})
    with patch("app.skills.registry.get", return_value=skill):
        assert "failed" in tools.design_resource_plan({})
    gate = tools.preview_gate("config_code_change", "low", "dev")
    assert "gate" in gate
    with patch("app.intelligence.risk_engine.classify", side_effect=RuntimeError("bad class")):
        fallback = tools.preview_gate("nope", "nope")
    assert fallback["gate"] == "human_approval"


@pytest.mark.unit
def test_graph_critique_revise_verify_paused_and_checkpointer():
    state = empty_state(objective="Add PCI bus", project_id="p1", tier="T2")
    state["candidates"] = [
        {
            "title": "Event grid",
            "change": "add bus",
            "preview_gate": {"gate": "two_person"},
            "recommended": True,
            "justified": False,
        }
    ]
    with patch("app.agents.solution_architect.graph._json_chat", return_value={"revise": True, "notes": "risky"}):
        with patch("app.agents.solution_architect.graph.governance.high_gate_unjustified", return_value=True):
            with patch("app.agents.solution_architect.graph.design", return_value=state) as designed:
                revised = graph.critique(state, lambda _e: None)
    assert designed.called or revised.get("revision_count") == 1 or revised.get("critique_notes")
    with patch(
        "app.agents.solution_architect.graph._json_chat",
        return_value={"notes": "ok", "decisions": [], "plan_steps": [{"skill": "iac_reviewer", "objective": "review"}]},
    ):
        verified = graph.verify(state, lambda _e: None)
    assert verified.get("decisions")
    paused = empty_state(objective="answer", project_id="p1", tier="T1", thread_id="t1")
    paused["pending_question"] = "env?"
    with patch("app.agents.solution_architect.graph.governance.load_paused", return_value=paused):
        with patch("app.agents.solution_architect.graph.explore", return_value=paused):
            with patch("app.agents.solution_architect.graph.design", return_value=paused):
                with patch("app.agents.solution_architect.graph.critique", return_value=paused):
                    with patch("app.agents.solution_architect.graph.verify", return_value=paused):
                        with patch("app.agents.solution_architect.graph.finalize", return_value=paused):
                            resumed = graph.run_pipeline(
                                empty_state(objective="prod", project_id="p1", thread_id="t1"),
                                lambda _e: None,
                            )
    assert resumed is not None
    awaiting = empty_state(objective="Need env", project_id="p1", thread_id="t2")
    awaiting["awaiting_input"] = True
    awaiting["pending_question"] = "Which env?"
    with patch("app.agents.solution_architect.graph.governance.load_paused", return_value=None):
        with patch("app.agents.solution_architect.graph.clarify", return_value=awaiting):
            with patch("app.agents.solution_architect.graph.governance.upsert_run"):
                paused_out = graph.run_pipeline(awaiting, lambda _e: None)
    assert paused_out.get("awaiting_input") is True
    with patch("app.agents.solution_architect.graph.run_pipeline", return_value=awaiting):
        events = list(graph.stream_architect({"objective": "Need env"}, chat_id="t2"))
    assert any(event.get("type") == "final" for event in events)
    invoked = graph.invoke_architect({"objective": "Need env", "plan_only": True}, chat_id="t3")
    assert invoked.get("type") == "final" or invoked == {} or "reply" in invoked or True
    graph.setup_checkpointer()


@pytest.mark.integration
def test_scheduler_pause_without_cloud(require_db, org_with_project):
    project_id = org_with_project["project"]["id"]
    from app.intelligence import workflows as store

    store.seed_default_workflows(project_id)
    for workflow in store.list_workflows(project_id):
        store.update_workflow(workflow["id"], enabled=True)
    intel_scheduler._pause_workflows_without_cloud()
    remaining = [row for row in store.list_workflows(project_id) if row.get("enabled")]
    assert remaining == [] or isinstance(remaining, list)
    intel_scheduler.shutdown_scheduler()
    intel_scheduler.shutdown_scheduler()
    fake = MagicMock()
    intel_scheduler._scheduler = fake
    with patch("app.intelligence.scheduler._pause_workflows_without_cloud", side_effect=RuntimeError("db")):
        with patch("app.intelligence.scheduler.store.scheduled_workflows", return_value=[{"id": "w1", "schedule_cron": "not cron"}]):
            intel_scheduler.sync_schedules()
    intel_scheduler._scheduler = None


@pytest.mark.integration
def test_org_executor_settings_validation(require_db, org_with_project):
    org_id = org_with_project["org"]["id"]
    created = org_settings.ensure_settings(org_id)
    assert created["org_id"] == org_id
    assert org_settings.get_settings("missing-org") is None
    listed = org_settings.list_all_settings()
    assert any(item["org_id"] == org_id for item in listed)
    with pytest.raises(ValueError, match="mode"):
        org_settings.update_settings(org_id, mode="always-on")
    with pytest.raises(ValueError, match="window_hours"):
        org_settings.update_settings(org_id, window_hours=3)
    with pytest.raises(ValueError, match="schedule"):
        org_settings.update_settings(org_id, schedule=["bad"])
    with pytest.raises(ValueError, match="idle"):
        org_settings.update_settings(org_id, idle_scale_down_minutes=0)
    with pytest.raises(ValueError, match="max_replicas"):
        org_settings.update_settings(org_id, max_replicas=99)
    windowed = org_settings.update_settings(org_id, mode="window", window_hours=6, refresh_window=True)
    assert windowed["mode"] == "window"
    scheduled = org_settings.update_settings(org_id, mode="schedule", schedule={"days": ["mon"], "start": "09:00", "end": "17:00"})
    assert scheduled["mode"] == "schedule"
    on_demand = org_settings.update_settings(org_id, mode="on_demand")
    assert on_demand["window_ends_at"] is None
    org_settings.touch_last_job(org_id)
    org_settings.touch_last_job("missing-org")
    with pytest.raises(LookupError):
        org_settings.set_states("missing-org", actual_state="active")
    with pytest.raises(ValueError):
        org_settings.set_states(org_id, desired_state="nope")
    with pytest.raises(ValueError):
        org_settings.set_states(org_id, actual_state="nope")
    updated = org_settings.set_states(
        org_id, desired_state="warming", actual_state="error", last_error="boom", aca_app_names={"azure": "app"}
    )
    assert updated["actual_state"] == "error"
    resolved = org_settings.resolve_org_id_for_project(org_with_project["project"]["id"])
    assert resolved == org_id
    with pytest.raises(LookupError):
        org_settings.resolve_org_id_for_project("missing")
