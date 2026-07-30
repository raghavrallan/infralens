"""Extra MVP coverage: actuators, memory shape, oauth options, gate map."""
from __future__ import annotations

from app import memory, module_actuators, oauth_providers, rbac


def test_gate_min_roles():
    assert rbac.GATE_MIN_ROLE["two_person"] == "devops_lead"
    assert rbac.GATE_MIN_ROLE["human_approval"] == "devops_engineer"


def test_oauth_options_always_offer_secrets():
    opts = oauth_providers.auth_options()
    assert "token" in opts["github"]["methods"] or "pat" in opts["github"]["methods"] or opts["github"]["pat"]
    assert opts["azure"]["secrets"] is True
    assert "client_secret" in opts["azure"]["methods"]


def test_module_actuators_pipeline_and_finops():
    user = {"role": "developer", "username": "dev"}
    finding = {
        "project_id": "default",
        "title": "CI flake",
        "resource": "acme/app",
        "evidence": "workflow failed",
        "recommended_action": "pin action versions",
        "blast_radius": "medium",
    }
    pipe = module_actuators.actuate("pipeline_intelligence", user=user, finding=finding)
    assert pipe["pr"]["status"] == "proposed"
    assert pipe["rollback"]
    rec = module_actuators.actuate("finops", user=user, finding=finding, mode="recommend")
    assert rec["gate"] == "autonomous"


def test_incident_mitigate_is_safety_direction():
    user = {"role": "developer", "username": "dev"}
    out = module_actuators.actuate(
        "incident_response",
        user=user,
        finding={"project_id": "default", "title": "spike", "evidence": "5xx"},
        tier="mitigate",
    )
    assert out["action_class"] == "safety_direction"


def test_memory_list_precedent_empty_ok():
    rows = memory.list_precedent("default", limit=3)
    assert isinstance(rows, list)
