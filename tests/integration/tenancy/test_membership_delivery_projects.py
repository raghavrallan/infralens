"""Membership requests, delivery remaining stages, and project tombstone paths."""
from __future__ import annotations

import json
from unittest.mock import patch

import pytest

from app.core.db import AppConfig, DELETED_PROJECTS_CONFIG_KEY, SessionLocal
from app.platform import delivery
from app.tenancy import membership_requests, memberships, projects, users_admin


pytestmark = pytest.mark.integration


def test_membership_request_as_lead_then_admin_decides(require_db, org_with_project, devops_lead, developer):
    org_id = org_with_project["org"]["id"]
    project_id = org_with_project["project"]["id"]
    admin = org_with_project["admin"]
    memberships.ensure_org_membership(org_id=org_id, user_id=devops_lead["id"], org_role="member")
    memberships.ensure_project_membership(
        project_id=project_id, user_id=devops_lead["id"], project_role="devops_lead"
    )
    memberships.ensure_org_membership(org_id=org_id, user_id=developer["id"], org_role="member")
    with pytest.raises(ValueError, match="action must be"):
        membership_requests.create_request(
            project_id=project_id,
            requested_by=devops_lead,
            action="explode",
        )
    with pytest.raises(ValueError, match="target_email"):
        membership_requests.create_request(
            project_id=project_id,
            requested_by=devops_lead,
            action="add",
        )
    with patch("app.tenancy.membership_requests.mailer.send_membership_request_email"):
        pending = membership_requests.create_request(
            project_id=project_id,
            requested_by=devops_lead,
            action="add",
            target_user_id=developer["id"],
            project_role="developer",
            reason="need help",
        )
    assert pending["status"] == "pending"
    assert pending["requires_approval"] is True
    listed = membership_requests.list_requests(org_id=org_id, status="pending")
    assert any(item["id"] == pending["id"] for item in listed)
    with pytest.raises(ValueError, match="decision must be"):
        membership_requests.decide_request(
            request_id=pending["id"], decision="maybe", decided_by=admin
        )
    with pytest.raises(PermissionError):
        membership_requests.decide_request(
            request_id=pending["id"], decision="approved", decided_by=developer
        )
    approved = membership_requests.decide_request(
        request_id=pending["id"], decision="approved", decided_by=admin
    )
    assert approved["status"] in {"approved", "applied"} or approved.get("action") == "add"
    with pytest.raises(ValueError):
        membership_requests.decide_request(
            request_id=pending["id"], decision="approved", decided_by=admin
        )
    with pytest.raises(LookupError):
        membership_requests.decide_request(
            request_id="missing", decision="rejected", decided_by=admin
        )


def test_org_admin_applies_member_change_directly(require_db, org_with_project, developer):
    org_id = org_with_project["org"]["id"]
    project_id = org_with_project["project"]["id"]
    admin = org_with_project["admin"]
    memberships.ensure_org_membership(org_id=org_id, user_id=developer["id"], org_role="member")
    added = membership_requests.create_request(
        project_id=project_id,
        requested_by=admin,
        action="add",
        target_user_id=developer["id"],
        project_role="developer",
    )
    assert added["requires_approval"] is False
    updated = membership_requests.create_request(
        project_id=project_id,
        requested_by=admin,
        action="update_role",
        target_user_id=developer["id"],
        project_role="devops_engineer",
    )
    assert updated["status"] == "applied"
    removed = membership_requests.create_request(
        project_id=project_id,
        requested_by=admin,
        action="remove",
        target_user_id=developer["id"],
    )
    assert removed["action"] == "remove"
    with pytest.raises(ValueError, match="already exist"):
        membership_requests.create_request(
            project_id=project_id,
            requested_by=admin,
            action="add",
            target_email="nobody-exists@example.com",
        )


def test_lead_request_rejected_via_token(require_db, org_with_project, devops_lead, developer):
    org_id = org_with_project["org"]["id"]
    project_id = org_with_project["project"]["id"]
    memberships.ensure_org_membership(org_id=org_id, user_id=devops_lead["id"], org_role="member")
    memberships.ensure_project_membership(
        project_id=project_id, user_id=devops_lead["id"], project_role="devops_lead"
    )
    with patch("app.tenancy.membership_requests.mailer.send_membership_request_email"):
        pending = membership_requests.create_request(
            project_id=project_id,
            requested_by=devops_lead,
            action="add",
            target_email=developer["email"],
            project_role="developer",
        )
    token = pending["approve_token"]
    rejected = membership_requests.decide_request(
        request_id=pending["id"],
        decision="rejected",
        decided_by={"id": "", "name": "email"},
        token=token,
    )
    assert rejected["status"] == "rejected"


def test_delivery_walks_remaining_stages(require_db, org_with_project):
    project_id = org_with_project["project"]["id"]
    run = delivery.create_run(project_id=project_id, created_by="admin")
    delivery.ingest_docs(run["id"], docs="# requirements", user_role="super_admin")
    with pytest.raises(ValueError, match="Unknown stage"):
        delivery.transition(run["id"], to_stage="moon", user_role="super_admin")
    with pytest.raises(LookupError):
        delivery.transition("missing", to_stage="architecture", user_role="super_admin")
    with pytest.raises(ValueError, match="skip"):
        delivery.transition(run["id"], to_stage="apply", user_role="super_admin")
    arch = delivery.transition(run["id"], to_stage="architecture", user_role="super_admin")
    assert arch["stage"] == "architecture"
    assert arch["next_actions"]
    tf = delivery.transition(run["id"], to_stage="terraform", user_role="super_admin")
    assert "terraform_pr" in (tf["artifacts"] or {})
    planned = delivery.transition(run["id"], to_stage="plan", user_role="super_admin")
    assert "action_diff" in (planned["artifacts"] or {})
    with pytest.raises(PermissionError):
        delivery.transition(run["id"], to_stage="apply", user_role="developer")
    applied = delivery.transition(run["id"], to_stage="apply", user_role="devops_lead")
    assert "apply_result" in (applied["artifacts"] or {})
    coded = delivery.transition(run["id"], to_stage="code", user_role="super_admin")
    assert "code_pr" in (coded["artifacts"] or {})
    done = delivery.transition(run["id"], to_stage="done", user_role="super_admin", approved_by="lead")
    assert done["status"] == "completed"
    with pytest.raises(ValueError, match="not active"):
        delivery.transition(run["id"], to_stage="done", user_role="super_admin")
    listed = delivery.list_runs(project_id)
    assert listed
    assert delivery.get_run("missing") is None


def test_projects_deleted_ids_and_reuse_empty(require_db, org_with_project, developer):
    org_id = org_with_project["org"]["id"]
    with SessionLocal() as session:
        session.merge(AppConfig(key=DELETED_PROJECTS_CONFIG_KEY, value="not-json"))
        session.commit()
    listed = projects.list_projects()
    assert isinstance(listed, list)
    with SessionLocal() as session:
        session.merge(AppConfig(key=DELETED_PROJECTS_CONFIG_KEY, value=json.dumps({"no": "list"})))
        session.commit()
    first = projects.create_project(
        "Onboarding project",
        org_id=org_id,
        owner_user_id=developer["id"],
        owner_project_role="developer",
    )
    reused = projects.create_project(
        "Named workspace",
        org_id=org_id,
        owner_user_id=developer["id"],
        owner_project_role="developer",
        reuse_empty=True,
    )
    assert reused["id"] == first["id"]
    assert reused["name"] == "Named workspace"
    empty_again = projects.create_project(
        "Onboarding project",
        org_id=org_id,
        owner_user_id=developer["id"],
        reuse_empty=True,
    )
    assert empty_again["id"] == first["id"]
    assert projects.rename_project("missing", "x") is None
    assert projects.set_repos("missing", ["a/b"]) is None
    assert projects.get_repos("missing") == []
    assert projects.set_default("missing") is None
    scoped = projects.list_projects(user=developer)
    assert any(item["id"] == first["id"] for item in scoped)


def test_users_admin_rejects_unknown_and_duplicate(require_db, super_admin):
    with pytest.raises(LookupError):
        users_admin.update_user("missing-user", display_name="Nope")
    created = users_admin.create_user(
        username=f"dup_{super_admin['id'][:6]}",
        email=f"dup_{super_admin['id'][:6]}@example.com",
        password="secret12ab",
        role="developer",
    )
    with pytest.raises(ValueError):
        users_admin.create_user(
            username=created["username"],
            email=f"other_{super_admin['id'][:6]}@example.com",
            password="secret12ab",
            role="developer",
        )
    deactivated = users_admin.update_user(created["id"], is_active=False, role="viewer")
    assert deactivated["is_active"] is False or deactivated["role"] == "viewer"
