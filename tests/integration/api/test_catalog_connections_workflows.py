"""Additional FastAPI routes: skills, catalog, connections, workflows, approvals."""
from __future__ import annotations

from unittest.mock import patch

import pytest


pytestmark = pytest.mark.integration


def _headers(org_with_project) -> dict[str, str]:
    return {"Authorization": f"Bearer {org_with_project['admin']['token']}"}


def test_skills_catalog_and_wiki(client, org_with_project):
    headers = _headers(org_with_project)
    listed = client.get("/api/skills", headers=headers)
    assert listed.status_code == 200
    names = {row["name"] for row in listed.json()}
    assert "cloud_posture" in names
    detail = client.get("/api/skills/cloud_posture", headers=headers)
    assert detail.status_code == 200
    assert detail.json()["wiki"] or detail.json()["description"]
    missing = client.get("/api/skills/not-real", headers=headers)
    assert missing.status_code == 404
    catalog = client.get("/api/intelligence/catalog", headers=headers)
    assert catalog.status_code == 200


def test_me_and_roles_and_azure_config(client, org_with_project):
    headers = _headers(org_with_project)
    me = client.get("/api/auth/me", headers=headers)
    assert me.status_code == 200
    assert me.json()["user"]
    roles = client.get("/api/roles", headers=headers)
    assert roles.status_code in {200, 404}
    cfg = client.get("/api/config/azure-openai", headers=headers)
    assert cfg.status_code == 200
    assert "configured" in cfg.json()


def test_project_connections_and_repos(client, org_with_project):
    headers = _headers(org_with_project)
    project_id = org_with_project["project"]["id"]
    listed = client.get(f"/api/projects/{project_id}/connections", headers=headers)
    assert listed.status_code == 200
    status = client.get(f"/api/projects/{project_id}/provider-status", headers=headers)
    assert status.status_code == 200
    saved = client.put(
        f"/api/projects/{project_id}/connections/azure",
        json={
            "method": "client_secret",
            "fields": {
                "tenant_id": "t",
                "client_id": "c",
                "client_secret": "s",
                "subscription_id": "sub",
            },
        },
        headers=headers,
    )
    assert saved.status_code == 200
    assert saved.json()["connected"] is True
    repos = client.get(f"/api/projects/{project_id}/repos", headers=headers)
    assert repos.status_code == 200
    updated = client.put(
        f"/api/projects/{project_id}/repos",
        json={"repos": ["acme/app"]},
        headers=headers,
    )
    assert updated.status_code in {200, 422}
    removed = client.delete(
        f"/api/projects/{project_id}/connections/azure",
        headers=headers,
    )
    assert removed.status_code == 200


def test_workflow_crud_and_approvals(client, org_with_project):
    headers = _headers(org_with_project)
    project_id = org_with_project["project"]["id"]
    created = client.post(
        f"/api/workflows?project_id={project_id}",
        json={
            "name": "Nightly posture",
            "skills": ["cloud_posture"],
            "objective": "scan",
            "module": "security_patch",
            "enabled": True,
        },
        headers=headers,
    )
    assert created.status_code == 200
    workflow_id = created.json()["id"]
    listed = client.get(f"/api/workflows?project_id={project_id}", headers=headers)
    assert any(row["id"] == workflow_id for row in listed.json())
    patched = client.patch(
        f"/api/workflows/{workflow_id}",
        json={"enabled": False},
        headers=headers,
    )
    assert patched.status_code == 200
    missing = client.patch("/api/workflows/missing", json={"enabled": True}, headers=headers)
    assert missing.status_code == 404
    with patch("app.intelligence.queue.enqueue_run"):
        run = client.post(f"/api/workflows/{workflow_id}/run", headers=headers)
    assert run.status_code in {200, 400, 403}
    approvals = client.get(f"/api/approvals?project_id={project_id}", headers=headers)
    assert approvals.status_code == 200
    arch = client.get(f"/api/architecture/runs?project_id={project_id}", headers=headers)
    assert arch.status_code in {200, 404}
    deleted = client.delete(f"/api/workflows/{workflow_id}", headers=headers)
    assert deleted.status_code == 200


def test_delivery_api_and_org_list(client, org_with_project):
    headers = _headers(org_with_project)
    project_id = org_with_project["project"]["id"]
    created = client.post(
        "/api/delivery/runs",
        json={"project_id": project_id},
        headers=headers,
    )
    assert created.status_code in {200, 404}
    listed = client.get(f"/api/delivery/runs?project_id={project_id}", headers=headers)
    assert listed.status_code in {200, 404}
    orgs = client.get("/api/orgs", headers=headers)
    assert orgs.status_code == 200
    smtp = client.get("/api/smtp/status", headers=headers)
    assert smtp.status_code in {200, 403}


def test_login_rejects_bad_password(client):
    response = client.post(
        "/api/auth/login",
        json={"username": "nobody", "password": "wrong-password"},
    )
    assert response.status_code in {401, 400}


def test_chat_stream_offline(client, org_with_project):
    headers = _headers(org_with_project)
    with patch("app.main.config.get_azure_config") as cfg:
        cfg.return_value.configured = False
        response = client.post(
            "/api/chat/stream",
            json={
                "message": "hello",
                "project_id": org_with_project["project"]["id"],
                "mode": "agent",
            },
            headers=headers,
        )
    assert response.status_code == 200
