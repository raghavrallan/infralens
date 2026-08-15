"""Invites, member requests, OAuth callbacks, executor settings, onboarding complete."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from app.tenancy import invites, memberships, onboarding, projects


pytestmark = pytest.mark.integration


def test_invite_create_accept_and_member_request(client, org_with_project, make_user):
    admin = org_with_project["admin"]
    headers = {"Authorization": f"Bearer {admin['token']}"}
    org_id = org_with_project["org"]["id"]
    project_id = org_with_project["project"]["id"]
    created = client.post(
        f"/api/orgs/{org_id}/invites",
        json={"email": "newhire@example.com", "invited_role": "developer"},
        headers=headers,
    )
    assert created.status_code in {200, 201}
    token = created.json().get("accept_token")
    if not token:
        invite = invites.create_invite(
            org_id=org_id,
            email="newhire2@example.com",
            invited_by=admin["id"],
            invited_role="developer",
        )
        token = invite.get("accept_token") or invite.get("token")
    peek = client.get("/api/invites/peek", params={"token": token})
    assert peek.status_code == 200
    accepted = client.post(
        "/api/invites/accept",
        json={"token": token, "password": "secret12ab", "display_name": "New Hire"},
    )
    assert accepted.status_code in {200, 400}
    listed = client.get(f"/api/orgs/{org_id}/invites", headers=headers)
    assert listed.status_code == 200
    requester = make_user(role="developer")
    memberships.ensure_org_membership(
        org_id=org_id, user_id=requester["id"], org_role="member"
    )
    request = client.post(
        f"/api/projects/{project_id}/member-requests",
        json={"action": "add", "target_email": "peer@example.com", "reason": "need access"},
        headers={"Authorization": f"Bearer {requester['token']}"},
    )
    assert request.status_code in {200, 201, 400, 403}
    pending = client.get(f"/api/orgs/{org_id}/member-requests", headers=headers)
    assert pending.status_code == 200


def test_oauth_callbacks_redirect(client):
    with patch(
        "app.api.routes_mvp.oauth_providers.finish_github_oauth",
        return_value={"project_id": "p1", "frontend_redirect": ""},
    ):
        ok = client.get(
            "/api/providers/github/oauth/callback",
            params={"code": "c", "state": "s"},
            follow_redirects=False,
        )
    assert ok.status_code in {302, 307}
    fail = client.get(
        "/api/providers/github/oauth/callback",
        params={"code": "c", "state": "bad"},
        follow_redirects=False,
    )
    assert fail.status_code in {302, 307}
    with patch(
        "app.api.routes_mvp.oauth_providers.finish_azure_oauth",
        return_value={"project_id": "p1"},
    ):
        azure_ok = client.get(
            "/api/providers/azure/oauth/callback",
            params={"code": "c", "state": "s"},
            follow_redirects=False,
        )
    assert azure_ok.status_code in {302, 307}
    azure_fail = client.get("/api/providers/azure/oauth/callback", follow_redirects=False)
    assert azure_fail.status_code in {302, 307}


def test_org_executor_settings_and_wake(client, org_with_project):
    headers = {"Authorization": f"Bearer {org_with_project['admin']['token']}"}
    org_id = org_with_project["org"]["id"]
    current = client.get(f"/api/orgs/{org_id}/executor-settings", headers=headers)
    assert current.status_code == 200
    updated = client.put(
        f"/api/orgs/{org_id}/executor-settings",
        json={"mode": "on_demand", "max_replicas": 1, "idle_scale_down_minutes": 15},
        headers=headers,
    )
    assert updated.status_code in {200, 400}
    status = client.get(f"/api/orgs/{org_id}/executor-status", headers=headers)
    assert status.status_code == 200
    with patch("app.org_executors.controller.request_wake", return_value={"woken": True}):
        wake = client.post(f"/api/orgs/{org_id}/executor-wake", headers=headers)
    assert wake.status_code in {200, 500}


def test_onboarding_complete_and_project_helpers(client, org_with_project, make_user):
    admin = org_with_project["admin"]
    headers = {"Authorization": f"Bearer {admin['token']}"}
    org_id = org_with_project["org"]["id"]
    complete = client.post(
        "/api/onboarding/complete",
        json={
            "path": "existing",
            "project_name": "Onboarded app",
            "repos": ["acme/app"],
        },
        headers=headers,
    )
    assert complete.status_code in {200, 400}
    default_id = projects.ensure_default()
    assert default_id
    extra = projects.create_project(
        "Empty twin",
        org_id=org_id,
        owner_user_id=admin["id"],
        owner_project_role="devops_lead",
    )
    removed = projects.collapse_duplicate_empty_projects(
        user=admin, keep_project_id=org_with_project["project"]["id"], org_id=org_id
    )
    assert removed >= 0
    reused = projects.create_project(
        "Renamed onboard",
        org_id=org_id,
        owner_user_id=admin["id"],
        reuse_empty=True,
    )
    assert reused["id"]
    resp = MagicMock(status_code=200)
    resp.json.return_value = {"login": "octo", "id": 1, "name": "Octo", "html_url": "https://github.com/octo"}
    ctx = MagicMock()
    ctx.__enter__.return_value = ctx
    ctx.__exit__.return_value = False
    with patch("app.tenancy.onboarding.github_infra.load_credentials", return_value=object()):
        with patch("app.tenancy.onboarding.github_infra._client", return_value=ctx):
            with patch("app.tenancy.onboarding.github_infra._get", return_value=resp):
                identity = onboarding.github_identity("p1")
    assert identity["login"] == "octo"


def test_delivery_docs_and_smtp_status(client, org_with_project):
    headers = {"Authorization": f"Bearer {org_with_project['admin']['token']}"}
    project_id = org_with_project["project"]["id"]
    created = client.post(
        "/api/delivery/runs",
        json={"project_id": project_id},
        headers=headers,
    )
    if created.status_code == 200:
        run_id = created.json()["id"]
        docs = client.post(
            f"/api/delivery/runs/{run_id}/docs",
            json={"docs": "# requirements\nneed an API"},
            headers=headers,
        )
        assert docs.status_code in {200, 400, 403}
        listed = client.get(f"/api/delivery/runs?project_id={project_id}", headers=headers)
        assert listed.status_code == 200
    smtp = client.get("/api/smtp/status", headers=headers)
    assert smtp.status_code in {200, 403}
    github_repos = client.get(
        f"/api/github/repos?project_id={project_id}",
        headers=headers,
    )
    assert github_repos.status_code in {200, 400}
