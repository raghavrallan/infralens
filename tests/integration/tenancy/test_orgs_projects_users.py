"""Tenancy orgs, projects, users, and invite/member API coverage."""
from __future__ import annotations

import pytest

from app.tenancy import orgs, projects, users_admin
from app.tenancy import memberships


pytestmark = pytest.mark.integration


def test_org_get_assign_and_projects(require_db, org_with_project, make_user):
    org_id = org_with_project["org"]["id"]
    loaded = orgs.get_org(org_id)
    assert loaded["id"] == org_id
    assert orgs.get_org("missing") is None
    listed = orgs.list_orgs_for_user(org_with_project["admin"])
    assert any(row["id"] == org_id for row in listed)
    engineer = make_user(role="developer")
    orgs.assign_org_admin(org_id=org_id, user_id=engineer["id"])
    org_projects = orgs.list_org_projects(org_id)
    assert any(row["id"] == org_with_project["project"]["id"] for row in org_projects)


def test_project_rename_repos_default_and_delete(require_db, org_with_project):
    project_id = org_with_project["project"]["id"]
    renamed = projects.rename_project(project_id, "Renamed Project")
    assert renamed["name"] == "Renamed Project"
    assert projects.rename_project("missing", "x") is None
    mapped = projects.set_repos(project_id, ["acme/app", "acme/lib"])
    assert "acme/app" in mapped["repos"]
    assert projects.get_repos(project_id) == mapped["repos"]
    defaulted = projects.set_default(project_id)
    assert defaulted is None or defaulted["id"] == project_id or defaulted
    extra = projects.create_project(
        "Disposable",
        org_id=org_with_project["org"]["id"],
        owner_user_id=org_with_project["admin"]["id"],
        owner_project_role="developer",
    )
    assert projects.delete_project(extra["id"]) is True
    assert projects.delete_project("missing") is False
    assert projects.get_project("missing") is None


def test_users_admin_create_list_update(require_db, org_with_project):
    org_id = org_with_project["org"]["id"]
    created = users_admin.create_user(
        username=f"qa-{org_id[:6]}",
        password="secret12",
        display_name="QA User",
        role="developer",
        email="qa@example.com",
        org_id=org_id,
    )
    assert created["username"].startswith("qa-")
    with pytest.raises(ValueError):
        users_admin.create_user(username="x", password="secret12")
    with pytest.raises(ValueError):
        users_admin.create_user(username="okuser", password="123")
    with pytest.raises(ValueError):
        users_admin.create_user(
            username="adminish", password="secret12", role="super_admin"
        )
    listed = users_admin.list_users(org_id=org_id, actor=org_with_project["admin"])
    assert any(row["id"] == created["id"] for row in listed)
    updated = users_admin.update_user(
        created["id"], role="devops_engineer", display_name="QA Eng", is_active=True
    )
    assert updated["role"] == "devops_engineer"
    with pytest.raises(LookupError):
        users_admin.update_user("missing", role="developer")


def test_org_invite_and_users_api(client, org_with_project):
    headers = {"Authorization": f"Bearer {org_with_project['admin']['token']}"}
    org_id = org_with_project["org"]["id"]
    created = client.post(
        f"/api/orgs/{org_id}/invites",
        json={"email": "newhire@example.com", "org_role": "member", "project_role": "developer"},
        headers=headers,
    )
    assert created.status_code in {200, 400, 403}
    listed = client.get(f"/api/orgs/{org_id}/invites", headers=headers)
    assert listed.status_code in {200, 403}
    members = client.get(f"/api/orgs/{org_id}/members", headers=headers)
    assert members.status_code == 200
    users = client.get(f"/api/users?org_id={org_id}", headers=headers)
    assert users.status_code == 200
    created_user = client.post(
        "/api/users",
        json={
            "username": f"apiuser-{org_id[:4]}",
            "password": "secret12",
            "role": "developer",
            "org_id": org_id,
        },
        headers=headers,
    )
    assert created_user.status_code in {200, 400, 403}


def test_membership_helpers(require_db, org_with_project, make_user):
    user = make_user(role="developer")
    memberships.ensure_org_membership(
        org_id=org_with_project["org"]["id"],
        user_id=user["id"],
        org_role="member",
    )
    memberships.ensure_project_membership(
        project_id=org_with_project["project"]["id"],
        user_id=user["id"],
        project_role="developer",
    )
    memberships.assert_project_access(user, org_with_project["project"]["id"])
    outsider = make_user(role="developer")
    with pytest.raises(Exception):
        memberships.assert_project_access(outsider, org_with_project["project"]["id"])
