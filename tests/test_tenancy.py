"""Tenancy isolation, invites, onboarding per-user, break-glass approve gate."""
from __future__ import annotations

import uuid

import pytest

from app.core import rbac
from app.tenancy import (
    invites,
    memberships,
    onboarding,
    orgs,
)
from app.platform import break_glass
from app.core.auth import hash_password
from app.core.db import (
    Organization,
    OrgMembership,
    Project,
    ProjectMembership,
    SessionLocal,
    User,
    init_db,
)

pytestmark = pytest.mark.infra


def _mk_user(*, username: str, role: str = "developer", email: str = "") -> dict:
    with SessionLocal() as session:
        row = User(
            id=str(uuid.uuid4()),
            username=username,
            email=email or f"{username}@example.com",
            display_name=username,
            password_hash=hash_password("secret12"),
            role=role,
            is_active=True,
        )
        session.add(row)
        session.commit()
        return {
            "id": row.id,
            "username": row.username,
            "name": row.display_name,
            "role": role,
            "email": row.email,
        }


def test_org_project_isolation(monkeypatch):
    init_db()
    admin = _mk_user(username=f"sa_{uuid.uuid4().hex[:8]}", role="super_admin")
    org_a = orgs.create_org(name=f"OrgA-{uuid.uuid4().hex[:6]}", created_by=admin["id"])
    org_b = orgs.create_org(name=f"OrgB-{uuid.uuid4().hex[:6]}", created_by=admin["id"])

    user_a = _mk_user(username=f"ua_{uuid.uuid4().hex[:8]}", role="developer")
    user_b = _mk_user(username=f"ub_{uuid.uuid4().hex[:8]}", role="developer")
    memberships.ensure_org_membership(org_id=org_a["id"], user_id=user_a["id"], org_role="member")
    memberships.ensure_org_membership(org_id=org_b["id"], user_id=user_b["id"], org_role="member")

    from app.tenancy import projects

    pa = projects.create_project(
        "ProjA", org_id=org_a["id"], owner_user_id=user_a["id"], owner_project_role="developer"
    )
    pb = projects.create_project(
        "ProjB", org_id=org_b["id"], owner_user_id=user_b["id"], owner_project_role="developer"
    )

    ids_a = {p["id"] for p in projects.list_projects(user=user_a)}
    ids_b = {p["id"] for p in projects.list_projects(user=user_b)}
    assert pa["id"] in ids_a
    assert pb["id"] not in ids_a
    assert pb["id"] in ids_b
    assert pa["id"] not in ids_b
    assert memberships.can_access_project(user_a, pa["id"])
    assert not memberships.can_access_project(user_a, pb["id"])


def test_onboarding_is_per_user():
    init_db()
    admin = _mk_user(username=f"admin_{uuid.uuid4().hex[:8]}", role="super_admin")
    org = orgs.create_org(name=f"Onboard-{uuid.uuid4().hex[:6]}", created_by=admin["id"])
    from app.tenancy import projects

    projects.create_project(
        "AdminProj",
        org_id=org["id"],
        owner_user_id=admin["id"],
        owner_project_role="devops_lead",
    )
    # Map a repo on admin project so global check would have falsely skipped.
    admin_projects = projects.list_projects(user=admin)
    if admin_projects:
        projects.set_repos(admin_projects[0]["id"], ["acme/admin-repo"])

    newbie = _mk_user(username=f"new_{uuid.uuid4().hex[:8]}", role="developer")
    memberships.ensure_org_membership(org_id=org["id"], user_id=newbie["id"], org_role="member")
    status = onboarding.status(user=newbie)
    assert status["needs_onboarding"] is True
    assert status["project_count"] == 0


def test_invite_accept_creates_membership():
    init_db()
    admin = _mk_user(username=f"invadmin_{uuid.uuid4().hex[:8]}", role="org_admin")
    org = orgs.create_org(name=f"InviteOrg-{uuid.uuid4().hex[:6]}", created_by=admin["id"])
    email = f"invitee_{uuid.uuid4().hex[:8]}@example.com"
    created = invites.create_invite(
        org_id=org["id"],
        email=email,
        invited_by=admin["id"],
        invited_role="developer",
        inviter_name="Admin",
    )
    token = created.get("accept_token")
    assert token, "SMTP may be down; create_invite must return accept_token when email not sent"
    result = invites.accept_invite(
        token=token,
        password="secret12",
        display_name="Invitee",
    )
    assert result["ok"] is True
    assert result["needs_onboarding"] is True
    assert memberships.org_membership(result["user_id"], org["id"]) is not None


def test_break_glass_effective_gate_for_approve():
    assert rbac.can_approve_gate({"role": "devops_engineer"}, "human_approval")
    assert not rbac.can_approve_gate({"role": "devops_engineer"}, "two_person")
    # After one-step downgrade, engineer can approve former two_person.
    effective = break_glass.downgrade_gate("two_person", "any", active=True)
    assert effective == "human_approval"
    assert rbac.can_approve_gate({"role": "devops_engineer"}, effective)


def test_lead_member_request_requires_approval_flag():
    init_db()
    admin = _mk_user(username=f"oa_{uuid.uuid4().hex[:8]}", role="org_admin")
    lead = _mk_user(username=f"lead_{uuid.uuid4().hex[:8]}", role="devops_lead")
    org = orgs.create_org(name=f"ReqOrg-{uuid.uuid4().hex[:6]}", created_by=admin["id"])
    memberships.ensure_org_membership(org_id=org["id"], user_id=lead["id"], org_role="member")
    from app.tenancy import projects
    from app.tenancy import membership_requests

    project = projects.create_project(
        "LeadProj",
        org_id=org["id"],
        owner_user_id=lead["id"],
        owner_project_role="devops_lead",
    )
    target = _mk_user(username=f"tgt_{uuid.uuid4().hex[:8]}", role="developer")
    memberships.ensure_org_membership(org_id=org["id"], user_id=target["id"], org_role="member")
    req = membership_requests.create_request(
        project_id=project["id"],
        requested_by=lead,
        action="add",
        target_user_id=target["id"],
        project_role="developer",
        reason="Need help on delivery",
    )
    assert req["requires_approval"] is True
    assert req["status"] == "pending"
    # Target not yet a project member
    assert memberships.project_membership(target["id"], project["id"]) is None
    decided = membership_requests.decide_request(
        request_id=req["id"],
        decision="approved",
        decided_by=admin,
    )
    assert decided["status"] == "approved"
    assert memberships.project_membership(target["id"], project["id"]) is not None
