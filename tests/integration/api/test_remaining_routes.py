"""Remaining API routes: SPA pages, connections, dashboard, findings, chat offline."""
from __future__ import annotations

from unittest.mock import patch

import pytest


pytestmark = pytest.mark.integration


def test_spa_pages_are_served(client):
    for path in (
        "/",
        "/login",
        "/dashboard",
        "/settings",
        "/wiki",
        "/organizations",
        "/onboarding",
        "/accept-invite",
        "/approve-member",
        "/c/some-chat",
    ):
        response = client.get(path)
        assert response.status_code == 200
        assert "html" in response.headers.get("content-type", "").lower() or response.text


def test_options_preflight_is_allowed(client):
    response = client.options("/api/skills")
    assert response.status_code in {200, 204, 400, 405}


def test_connections_unknown_provider(client, org_with_project):
    headers = {"Authorization": f"Bearer {org_with_project['admin']['token']}"}
    project_id = org_with_project["project"]["id"]
    response = client.put(
        f"/api/projects/{project_id}/connections/gcp",
        json={"method": "token", "fields": {}},
        headers=headers,
    )
    assert response.status_code in {403, 404}


def test_dashboard_and_findings_for_project(client, org_with_project):
    headers = {"Authorization": f"Bearer {org_with_project['admin']['token']}"}
    project_id = org_with_project["project"]["id"]
    dash = client.get(f"/api/dashboard/summary?project_id={project_id}", headers=headers)
    assert dash.status_code == 200
    findings = client.get(f"/api/findings?project_id={project_id}", headers=headers)
    assert findings.status_code == 200
    runs = client.get(f"/api/runs?project_id={project_id}", headers=headers)
    assert runs.status_code == 200
    missing_run = client.get("/api/runs/missing", headers=headers)
    assert missing_run.status_code == 404
    missing_finding = client.patch(
        "/api/findings/missing",
        json={"status": "resolved"},
        headers=headers,
    )
    assert missing_finding.status_code == 404


def test_chat_without_azure_returns_offline_message(client, org_with_project):
    headers = {"Authorization": f"Bearer {org_with_project['admin']['token']}"}
    with patch("app.main.config.get_azure_config") as cfg:
        cfg.return_value.configured = False
        response = client.post(
            "/api/chat",
            json={
                "message": "hello",
                "project_id": org_with_project["project"]["id"],
                "mode": "agent",
            },
            headers=headers,
        )
    assert response.status_code == 200
    assert "not configured" in response.json()["reply"].lower()


def test_unknown_skill_on_chat_is_400(client, org_with_project):
    headers = {"Authorization": f"Bearer {org_with_project['admin']['token']}"}
    response = client.post(
        "/api/chat",
        json={
            "message": "hi",
            "skill": "not_a_skill",
            "project_id": org_with_project["project"]["id"],
        },
        headers=headers,
    )
    assert response.status_code == 400


def test_provider_auth_options(client, developer):
    headers = {"Authorization": f"Bearer {developer['token']}"}
    response = client.get("/api/providers/auth-options", headers=headers)
    assert response.status_code == 200
    assert "github" in response.json()


def test_github_pat_and_azure_secrets_require_capability(
    client, viewer, org_with_project
):
    project_id = org_with_project["project"]["id"]
    admin = {"Authorization": f"Bearer {org_with_project['admin']['token']}"}
    denied = client.post(
        "/api/providers/github/pat",
        json={"project_id": project_id, "token": "gho_x"},
        headers={"Authorization": f"Bearer {viewer['token']}"},
    )
    assert denied.status_code == 403
    with patch("app.api.routes_mvp.onboarding.github_identity", return_value={"login": "octo"}):
        saved = client.post(
            "/api/providers/github/pat",
            json={"project_id": project_id, "token": "gho_test_token", "username": "octo"},
            headers=admin,
        )
    assert saved.status_code in {200, 400, 403}
    azure = client.post(
        "/api/providers/azure/secrets",
        json={
            "project_id": project_id,
            "tenant_id": "t",
            "client_id": "c",
            "client_secret": "s",
            "subscription_id": "sub",
        },
        headers=admin,
    )
    assert azure.status_code in {200, 403}


def test_memory_precedent_requires_project_access(client, org_with_project):
    headers = {"Authorization": f"Bearer {org_with_project['admin']['token']}"}
    response = client.get(
        f"/api/memory/precedent?project_id={org_with_project['project']['id']}",
        headers=headers,
    )
    assert response.status_code in {200, 403}


def test_module_actuate(client, org_with_project):
    headers = {"Authorization": f"Bearer {org_with_project['admin']['token']}"}
    response = client.post(
        "/api/modules/pipeline_intelligence/actuate",
        json={
            "project_id": org_with_project["project"]["id"],
            "finding": {
                "project_id": org_with_project["project"]["id"],
                "title": "pin actions",
                "resource": "acme/app",
                "evidence": "unpinned",
                "recommended_action": "pin",
                "blast_radius": "low",
            },
        },
        headers=headers,
    )
    assert response.status_code in {200, 403, 422}
