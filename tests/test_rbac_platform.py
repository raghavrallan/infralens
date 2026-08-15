"""RBAC, rollback gate, onboarding, break-glass, and delivery tests."""
from __future__ import annotations

from unittest.mock import patch

from app.core import rbac
from app.tenancy import onboarding
from app.platform import (
    break_glass,
    delivery,
)
from app.execution import service as execution
from app.execution.validation import validate_operation


def test_role_hierarchy():
    assert rbac.has_min_role("super_admin", "viewer")
    assert rbac.has_min_role("devops_lead", "devops_engineer")
    assert not rbac.has_min_role("developer", "devops_lead")
    assert rbac.can({"role": "viewer"}, "read")
    assert not rbac.can({"role": "viewer"}, "propose_write")
    assert rbac.can_approve_gate({"role": "devops_lead"}, "two_person")
    assert not rbac.can_approve_gate({"role": "developer"}, "two_person")


def test_write_requires_rollback_fields():
    try:
        execution.create_action(
            project_id="default",
            provider="azure",
            executable="az",
            args=["account", "show"],
            target="subscription",
            access_scope="write",
            expected_result="",
            risk="",
            rollback="",
            preflight=["account", "show"],
            verify=["account", "show"],
        )
        assert False, "expected ValueError"
    except ValueError as exc:
        assert "rollback" in str(exc).lower() or "risk" in str(exc).lower() or "expected" in str(exc).lower()


def test_validate_operation_still_requires_preflight_for_write():
    try:
        validate_operation(
            "azure",
            "az",
            ["group", "create", "-n", "x", "-l", "eastus"],
            "rg/x",
            "write",
            None,
            None,
        )
        assert False, "expected ValueError"
    except ValueError as exc:
        assert "preflight" in str(exc).lower() or "verification" in str(exc).lower()


def test_onboarding_paths_shape():
    with patch("app.tenancy.onboarding.projects.list_projects", return_value=[]):
        with patch("app.tenancy.onboarding.memberships.primary_org_id", return_value=None):
            status = onboarding.status(
                user={"id": "u", "username": "a", "name": "A", "role": "developer"}
            )
    assert "paths" in status
    assert {p["id"] for p in status["paths"]} == {"existing", "new"}


def test_break_glass_one_step_downgrade(monkeypatch):
    monkeypatch.setattr(break_glass, "is_active", lambda _pid: True)
    assert break_glass.downgrade_gate("two_person", "default") == "human_approval"
    assert break_glass.downgrade_gate("human_approval", "default") == "auto_apply"
    monkeypatch.setattr(break_glass, "is_active", lambda _pid: False)
    assert break_glass.downgrade_gate("two_person", "default") == "two_person"


def test_delivery_stage_order():
    assert delivery.STAGES[0] == "ingest"
    assert delivery.STAGES[-1] == "done"
    assert delivery.STAGE_MIN_ROLE["apply"] == "devops_lead"
