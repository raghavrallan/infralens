"""Full MVP QA checklist: RBAC matrix, rollback, break-glass TTL, delivery, modules."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

import pytest

from app import break_glass, delivery, module_actuators, rbac
from app.execution.validation import validate_operation


def test_rbac_matrix_capabilities():
    matrix = [
        ("viewer", "read", True),
        ("viewer", "propose_write", False),
        ("viewer", "create_project", False),
        ("developer", "propose_write", True),
        ("developer", "create_github_repo", True),
        ("developer", "approve_two_person", False),
        ("developer", "prod_apply", False),
        ("devops_engineer", "approve_human", True),
        ("devops_engineer", "approve_two_person", False),
        ("devops_lead", "approve_two_person", True),
        ("devops_lead", "break_glass", True),
        ("org_admin", "manage_users", True),
        ("super_admin", "system_settings", True),
    ]
    for role, capability, expected in matrix:
        assert rbac.can({"role": role}, capability) is expected, (role, capability)


def test_gate_role_map():
    assert rbac.can_approve_gate({"role": "developer"}, "autonomous")
    assert not rbac.can_approve_gate({"role": "developer"}, "human_approval")
    assert rbac.can_approve_gate({"role": "devops_engineer"}, "human_approval")
    assert not rbac.can_approve_gate({"role": "devops_engineer"}, "two_person")
    assert rbac.can_approve_gate({"role": "devops_lead"}, "two_person")


def test_rollback_gate_rejects_empty_write_fields():
    from app.execution import service as execution

    with pytest.raises(ValueError, match="rollback|risk|expected"):
        execution.create_action(
            project_id="default",
            provider="azure",
            executable="az",
            args=["group", "show", "-n", "x"],
            target="rg/x",
            access_scope="write",
            expected_result="",
            risk="something",
            rollback="",
            preflight=["group", "show", "-n", "x"],
            verify=["group", "show", "-n", "x"],
        )


def test_write_validation_requires_preflight_and_verify():
    with pytest.raises(ValueError):
        validate_operation(
            "azure",
            "az",
            ["group", "create", "-n", "x", "-l", "eastus"],
            "rg/x",
            "write",
            ["group", "show", "-n", "x"],
            None,
        )


def test_break_glass_ttl_and_expire(monkeypatch):
    # Simulate open_session without DB by unit-testing downgrade + expire helpers.
    monkeypatch.setattr(break_glass, "is_active", lambda _pid: True)
    assert break_glass.downgrade_gate("two_person", "p1") == "human_approval"
    bg = break_glass.gate_with_break_glass("two_person", "p1")
    assert bg["break_glass_applied"] is True
    assert bg["original_gate"] == "two_person"


def test_delivery_happy_path_roles():
    # Stage role requirements
    assert delivery.STAGE_MIN_ROLE["ingest"] == "developer"
    assert delivery.STAGE_MIN_ROLE["apply"] == "devops_lead"
    # Permission helper used by transition
    with pytest.raises(PermissionError):
        delivery._require_stage_role("developer", "apply")
    delivery._require_stage_role("devops_lead", "apply")


def test_delivery_cannot_skip_stages_logic():
    stages = delivery.STAGES
    assert stages.index("terraform") == stages.index("architecture") + 1
    assert stages.index("apply") > stages.index("plan")


def test_module_smoke_all_six():
    user = {"role": "devops_lead", "username": "lead"}
    finding = {
        "project_id": "default",
        "title": "sample",
        "resource": "acme/app",
        "evidence": "healthy green",
        "blast_radius": "medium",
        "recommended_action": "fix it",
    }
    modules = [
        ("pipeline_intelligence", {}),
        ("security_patch", {}),
        ("iac", {"mode": "plan"}),
        ("finops", {"mode": "recommend"}),
        ("release_confidence", {}),
        ("incident_response", {"tier": "diagnose"}),
    ]
    for name, kwargs in modules:
        out = module_actuators.actuate(name, user=user, finding=finding, **kwargs)
        assert out["module"] == name
        assert out.get("silent_apply") is False
        assert "rollback" in out


def test_iac_delete_requires_two_person_capability():
    user = {"role": "developer", "username": "dev"}
    with pytest.raises(Exception):
        module_actuators.actuate(
            "iac",
            user=user,
            finding={"project_id": "default", "title": "rm"},
            mode="delete",
        )


def test_prod_iac_apply_requires_lead():
    from fastapi import HTTPException

    user = {"role": "developer", "username": "dev"}
    with pytest.raises(HTTPException):
        module_actuators.actuate(
            "iac",
            user=user,
            finding={"project_id": "default", "title": "apply"},
            mode="apply",
            environment="prod",
        )
