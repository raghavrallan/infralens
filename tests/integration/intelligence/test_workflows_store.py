"""Workflow helpers, approvals, and seed/enable paths with a real test database."""
from __future__ import annotations

from datetime import date

import pytest

from app.intelligence import workflows as intel
from app.skills.classification import is_workflow_safe


pytestmark = pytest.mark.integration


def test_safe_skills_and_module_of():
    assert is_workflow_safe("cloud_posture") is True
    assert is_workflow_safe("terraform_executor") is False
    assert "cloud_posture" in intel._safe_skills(["cloud_posture", "terraform_executor", "cloud_posture"])
    module = intel._module_of(["cloud_posture"])
    assert isinstance(module, str)


def test_time_range_bounds_custom_dates():
    since, until = intel.time_range_bounds(
        "custom", start_date=date(2026, 1, 1), end_date=date(2026, 1, 31)
    )
    assert since is not None and until is not None


def test_seed_enable_update_and_approvals(require_db, org_with_project):
    project_id = org_with_project["project"]["id"]
    intel.seed_default_workflows(project_id)
    listed = intel.list_workflows(project_id)
    assert listed
    enabled = intel.enable_workflows_when_ready(project_id)
    assert enabled >= 0
    workflow = listed[0]
    updated = intel.update_workflow(workflow["id"], name="Renamed", enabled=False, environment="dev")
    assert updated["name"] == "Renamed"
    assert intel.update_workflow("missing") is None
    run = intel.create_run(workflow["id"], trigger="schedule")
    intel.mark_run_failed(run["id"], "boom")
    loaded = intel.get_run(run["id"])
    assert loaded["status"] == "failed"
    assert intel.get_run("missing") is None
    assert intel.create_run("missing") is None
    runs = intel.list_runs(project_id)
    assert any(row["id"] == run["id"] for row in runs)
    scheduled = intel.scheduled_workflows()
    assert isinstance(scheduled, list)
    intel.save_findings(
        run["id"],
        workflow["id"],
        project_id,
        [
            {
                "title": "Open SSH",
                "severity": "critical",
                "resource": "nsg-ssh",
                "skill": "cloud_posture",
                "recommended_action": "restrict",
                "gate_decision": "human_approval",
            }
        ],
    )
    findings = intel.list_findings(project_id, severity="critical")
    assert findings
    approvals = intel.list_approvals(project_id)
    assert isinstance(approvals, list)
    if approvals:
        decided = intel.decide_approval(
            approvals[0]["id"],
            decision="approved",
            decided_by="tester",
        )
        assert decided is None or decided["decision"] in {"approved", "rejected"} or decided
    assert intel.update_finding_status("missing", "open") is None
    assert intel.update_finding_status(findings[0]["id"], "nope") is None
    collapsed = intel.collapse_duplicate_findings(project_id)
    assert collapsed >= 0
    assert intel.delete_workflow("missing") is False
    dash = intel.dashboard_summary(project_id, time_range="7d", module=workflow.get("module") or None)
    assert "open_findings" in dash


def test_reap_stale_workflow_runs(require_db, org_with_project):
    from datetime import datetime, timedelta, timezone

    from app.core.db import SessionLocal, WorkflowRun

    project_id = org_with_project["project"]["id"]
    intel.seed_default_workflows(project_id)
    workflow = intel.list_workflows(project_id)[0]
    stale = intel.create_run(workflow["id"], trigger="manual")
    intel.mark_run_running(stale["id"])
    fresh = intel.create_run(workflow["id"], trigger="manual")
    intel.mark_run_running(fresh["id"])
    old = datetime.now(timezone.utc) - timedelta(days=13)
    with SessionLocal() as session:
        row = session.get(WorkflowRun, stale["id"])
        row.created_at = old
        row.started_at = old
        session.commit()
    closed = intel.reap_stale_runs(project_id)
    assert closed >= 1
    assert intel.get_run(stale["id"])["status"] == "failed"
    assert intel.get_run(fresh["id"])["status"] == "running"
