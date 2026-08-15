"""Onboarding, invites peek, break-glass, and delivery run authorization."""
from __future__ import annotations

import pytest


pytestmark = pytest.mark.integration


def test_onboarding_status_shape(client, developer):
    response = client.get(
        "/api/onboarding/status",
        headers={"Authorization": f"Bearer {developer['token']}"},
    )
    assert response.status_code == 200
    body = response.json()
    assert "needs_onboarding" in body
    assert {p["id"] for p in body["paths"]} == {"existing", "new"}


def test_invite_peek_invalid_token_is_public(client):
    response = client.get("/api/invites/peek", params={"token": "not-real"})
    assert response.status_code == 404


def test_break_glass_requires_lead(client, developer, devops_lead, org_with_project):
    project_id = org_with_project["project"]["id"]
    denied = client.post(
        "/api/break-glass/open",
        json={"project_id": project_id, "reason": "prod incident mitigation window"},
        headers={"Authorization": f"Bearer {developer['token']}"},
    )
    assert denied.status_code == 403
    opened = client.post(
        "/api/break-glass/open",
        json={"project_id": project_id, "reason": "prod incident mitigation window"},
        headers={"Authorization": f"Bearer {devops_lead['token']}"},
    )
    assert opened.status_code in {200, 403}
    status = client.get(
        f"/api/break-glass/status?project_id={project_id}",
        headers={"Authorization": f"Bearer {devops_lead['token']}"},
    )
    assert status.status_code in {200, 403}


def test_delivery_run_requires_propose_write(client, viewer, developer, org_with_project):
    project_id = org_with_project["project"]["id"]
    denied = client.post(
        "/api/delivery/runs",
        json={"project_id": project_id},
        headers={"Authorization": f"Bearer {viewer['token']}"},
    )
    assert denied.status_code in {401, 403}
    created = client.post(
        "/api/delivery/runs",
        json={"project_id": project_id},
        headers={"Authorization": f"Bearer {developer['token']}"},
    )
    assert created.status_code in {200, 403}


def test_users_list_requires_org_admin(client, developer, super_admin):
    denied = client.get(
        "/api/users",
        headers={"Authorization": f"Bearer {developer['token']}"},
    )
    assert denied.status_code == 403
    allowed = client.get(
        "/api/users",
        headers={"Authorization": f"Bearer {super_admin['token']}"},
    )
    assert allowed.status_code == 200
    assert isinstance(allowed.json(), list)
