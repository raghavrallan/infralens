"""RBAC hierarchy, aliases, capabilities, and FastAPI guards."""
from __future__ import annotations

import pytest
from fastapi import HTTPException

from app.core import rbac


@pytest.mark.unit
def test_normalize_role_aliases_and_unknown():
    assert rbac.normalize_role("admin") == "super_admin"
    assert rbac.normalize_role("superadmin") == "super_admin"
    assert rbac.normalize_role("Org Admin") == "org_admin"
    assert rbac.normalize_role("lead") == "devops_lead"
    assert rbac.normalize_role("engineer") == "devops_engineer"
    assert rbac.normalize_role("dev") == "developer"
    assert rbac.normalize_role("readonly") == "viewer"
    assert rbac.normalize_role("read-only") == "viewer"
    assert rbac.normalize_role(None) == "developer"
    assert rbac.normalize_role("") == "developer"
    assert rbac.normalize_role("not-a-role") == "developer"


@pytest.mark.unit
def test_role_rank_order():
    ranks = [rbac.role_rank(role) for role in rbac.ROLE_ORDER]
    assert ranks == sorted(ranks)
    assert rbac.role_rank("super_admin") > rbac.role_rank("viewer")
    assert rbac.role_rank("unknown") == rbac.role_rank("developer")


@pytest.mark.unit
@pytest.mark.parametrize(
    "role,minimum,expected",
    [
        ("viewer", "viewer", True),
        ("viewer", "developer", False),
        ("developer", "viewer", True),
        ("devops_lead", "devops_engineer", True),
        ("org_admin", "super_admin", False),
        ("super_admin", "org_admin", True),
    ],
)
def test_has_min_role(role, minimum, expected):
    assert rbac.has_min_role(role, minimum) is expected


@pytest.mark.unit
def test_unknown_capability_requires_super_admin():
    assert not rbac.can({"role": "org_admin"}, "not_a_real_capability")
    assert rbac.can({"role": "super_admin"}, "not_a_real_capability")


@pytest.mark.unit
def test_every_capability_has_a_defined_minimum():
    for capability, minimum in rbac.CAPABILITY_MIN_ROLE.items():
        assert minimum in rbac.ROLE_LABELS
        assert rbac.can({"role": "super_admin"}, capability)


@pytest.mark.unit
def test_assert_capability_raises_http_403():
    with pytest.raises(HTTPException) as exc:
        rbac.assert_capability({"role": "viewer"}, "propose_write")
    assert exc.value.status_code == 403
    assert "role" in exc.value.detail.lower() or "Requires" in exc.value.detail


@pytest.mark.unit
def test_assert_capability_allows_when_permitted():
    rbac.assert_capability({"role": "developer"}, "propose_write")


@pytest.mark.unit
def test_can_approve_gate_unknown_defaults_to_lead():
    assert not rbac.can_approve_gate({"role": "developer"}, "mystery_gate")
    assert rbac.can_approve_gate({"role": "devops_lead"}, "mystery_gate")


@pytest.mark.unit
def test_public_roles_covers_hierarchy():
    ids = {item["id"] for item in rbac.public_roles()}
    assert ids == set(rbac.ROLE_LABELS)
    assert all("label" in item for item in rbac.public_roles())


@pytest.mark.unit
def test_require_capability_dependency_rejects():
    dep = rbac.require_capability("manage_users")
    with pytest.raises(HTTPException) as exc:
        dep(user={"role": "developer", "id": "u1"})
    assert exc.value.status_code == 403


@pytest.mark.unit
def test_require_capability_dependency_allows():
    dep = rbac.require_capability("read")
    user = {"role": "viewer", "id": "u1"}
    assert dep(user=user) is user


@pytest.mark.unit
def test_require_min_role_dependency():
    dep = rbac.require_min_role("org_admin")
    with pytest.raises(HTTPException) as exc:
        dep(user={"role": "developer"})
    assert exc.value.status_code == 403
    assert dep(user={"role": "org_admin"})["role"] == "org_admin"
