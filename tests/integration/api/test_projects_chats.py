"""Project tenancy, chats, and Azure config authorization."""
from __future__ import annotations

import pytest


pytestmark = pytest.mark.integration


def test_super_admin_can_create_and_list_projects(client, super_admin):
    headers = {"Authorization": f"Bearer {super_admin['token']}"}
    created = client.post("/api/projects", json={"name": "Alpha"}, headers=headers)
    assert created.status_code == 200
    project = created.json()
    assert project["name"] == "Alpha"
    listed = client.get("/api/projects", headers=headers)
    assert listed.status_code == 200
    ids = {row["id"] for row in listed.json()}
    assert project["id"] in ids


def test_developer_cannot_see_other_org_project(
    client, super_admin, make_user
):
    from app.tenancy import memberships, orgs, projects

    headers_admin = {"Authorization": f"Bearer {super_admin['token']}"}
    org_a = orgs.create_org(name="OrgA-iso", created_by=super_admin["id"])
    org_b = orgs.create_org(name="OrgB-iso", created_by=super_admin["id"])
    user_a = make_user(role="developer")
    user_b = make_user(role="developer")
    memberships.ensure_org_membership(org_id=org_a["id"], user_id=user_a["id"], org_role="member")
    memberships.ensure_org_membership(org_id=org_b["id"], user_id=user_b["id"], org_role="member")
    pa = projects.create_project(
        "OnlyA", org_id=org_a["id"], owner_user_id=user_a["id"], owner_project_role="developer"
    )
    listed = client.get(
        "/api/projects",
        headers={"Authorization": f"Bearer {user_b['token']}"},
    )
    ids = {row["id"] for row in listed.json()}
    assert pa["id"] not in ids
    # Admin listing still works
    admin_list = client.get("/api/projects", headers=headers_admin)
    assert admin_list.status_code == 200


def test_cannot_delete_default_project(client, super_admin, org_with_project):
    from app.tenancy import projects as project_store

    headers = {"Authorization": f"Bearer {super_admin['token']}"}
    default = next(
        (p for p in project_store.list_projects(user=super_admin) if p.get("is_default")),
        None,
    )
    if default is None:
        pytest.skip("no default project seeded")
    response = client.delete(f"/api/projects/{default['id']}", headers=headers)
    assert response.status_code in {400, 403}


def test_chat_crud(client, developer, org_with_project):
    headers = {"Authorization": f"Bearer {developer['token']}"}
    project_id = org_with_project["project"]["id"]
    created = client.post(f"/api/chats?project_id={project_id}", headers=headers)
    assert created.status_code == 200
    chat_id = created.json()["id"]
    listed = client.get(f"/api/chats?project_id={project_id}", headers=headers)
    assert any(row["id"] == chat_id for row in listed.json())
    renamed = client.patch(
        f"/api/chats/{chat_id}", json={"title": "Renamed"}, headers=headers
    )
    assert renamed.status_code == 200
    assert renamed.json()["title"] == "Renamed"
    missing = client.get("/api/chats/does-not-exist", headers=headers)
    assert missing.status_code == 404
    deleted = client.delete(f"/api/chats/{chat_id}", headers=headers)
    assert deleted.status_code == 200
    assert deleted.json()["deleted"] is True


def test_azure_openai_config_is_super_admin_write(
    client, developer, super_admin
):
    dev_headers = {"Authorization": f"Bearer {developer['token']}"}
    admin_headers = {"Authorization": f"Bearer {super_admin['token']}"}
    denied = client.put(
        "/api/config/azure-openai",
        json={"endpoint": "https://example", "api_key": "k"},
        headers=dev_headers,
    )
    assert denied.status_code == 403
    allowed = client.put(
        "/api/config/azure-openai",
        json={
            "endpoint": "https://example.openai.azure.com",
            "api_key": "test-key",
            "deployment": "gpt-4o",
            "api_version": "2024-10-21",
        },
        headers=admin_headers,
    )
    assert allowed.status_code == 200
    body = allowed.json()
    assert body["configured"] is True
    assert "test-key" not in str(body)
    listed = client.get("/api/config/azure-openai", headers=dev_headers)
    assert listed.status_code == 200
    assert listed.json()["has_key"] is True
