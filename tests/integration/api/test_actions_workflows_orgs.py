"""Executor control-plane auth, action preview, and workflow catalog."""
from __future__ import annotations

from unittest.mock import patch

import pytest


pytestmark = pytest.mark.integration


def test_executor_claim_rejects_bad_credentials(client, org_with_project):
    action_id = "missing-action"
    response = client.get(
        f"/internal/execution/jobs/{action_id}/claim",
        params={"provider": "azure"},
        headers={
            "X-Executor-Key": "wrong-key",
            "X-Executor-Provider": "azure",
            "X-Executor-Org-Id": org_with_project["org"]["id"],
        },
    )
    assert response.status_code == 403


def test_executor_claim_rejects_missing_org(client):
    response = client.get(
        "/internal/execution/jobs/x/claim",
        params={"provider": "azure"},
        headers={
            "X-Executor-Key": "test-executor-key",
            "X-Executor-Provider": "azure",
        },
    )
    assert response.status_code == 403


def test_executor_event_rejects_unsupported_type(client, org_with_project):
    response = client.post(
        "/internal/execution/jobs/x/events",
        json={"type": "not-allowed", "payload": {}},
        headers={
            "X-Executor-Key": "test-executor-key",
            "X-Executor-Provider": "azure",
            "X-Executor-Org-Id": org_with_project["org"]["id"],
        },
    )
    assert response.status_code == 400


def test_action_preview_validates_operation(client, developer, org_with_project):
    headers = {"Authorization": f"Bearer {developer['token']}"}
    response = client.post(
        "/api/actions/preview",
        json={
            "project_id": org_with_project["project"]["id"],
            "provider": "azure",
            "executable": "az",
            "args": ["account", "show", "--output", "json"],
            "target": "identity",
            "access_scope": "read_only",
        },
        headers=headers,
    )
    assert response.status_code == 200
    body = response.json()
    assert body["operation"]["executable"] == "az"
    assert body["approval_required"] is False


def test_action_preview_rejects_shell_syntax(client, developer, org_with_project):
    headers = {"Authorization": f"Bearer {developer['token']}"}
    response = client.post(
        "/api/actions/preview",
        json={
            "project_id": org_with_project["project"]["id"],
            "provider": "azure",
            "executable": "az",
            "args": ["account", "show | cat"],
            "target": "identity",
            "access_scope": "read_only",
        },
        headers=headers,
    )
    assert response.status_code == 400


def test_missing_action_returns_404(client, developer):
    headers = {"Authorization": f"Bearer {developer['token']}"}
    response = client.get("/api/actions/does-not-exist", headers=headers)
    assert response.status_code == 404


def test_intelligence_catalog_and_workflow_crud(client, developer, org_with_project):
    headers = {"Authorization": f"Bearer {developer['token']}"}
    project_id = org_with_project["project"]["id"]
    catalog = client.get("/api/intelligence/catalog", headers=headers)
    assert catalog.status_code == 200
    assert catalog.json()["modules"]
    created = client.post(
        f"/api/workflows?project_id={project_id}",
        json={
            "name": "Nightly posture",
            "skills": ["cloud_posture", "terraform_executor"],
            "module": "security_patch",
            "enabled": True,
        },
        headers=headers,
    )
    assert created.status_code == 200
    workflow = created.json()
    # terraform_executor is not workflow-safe and must be stripped.
    assert "terraform_executor" not in workflow.get("skills", [])
    listed = client.get(f"/api/workflows?project_id={project_id}", headers=headers)
    assert listed.status_code == 200
    patched = client.patch(
        f"/api/workflows/{workflow['id']}",
        json={"enabled": False},
        headers=headers,
    )
    assert patched.status_code == 200
    assert patched.json()["enabled"] is False
    missing = client.patch(
        "/api/workflows/missing",
        json={"enabled": True},
        headers=headers,
    )
    assert missing.status_code == 404
    deleted = client.delete(f"/api/workflows/{workflow['id']}", headers=headers)
    assert deleted.status_code == 200


def test_run_workflow_requires_cloud_connection(
    client, super_admin, org_with_project
):
    headers = {"Authorization": f"Bearer {super_admin['token']}"}
    project_id = org_with_project["project"]["id"]
    created = client.post(
        f"/api/workflows?project_id={project_id}",
        json={"name": "Run me", "skills": ["cloud_posture"], "enabled": True},
        headers=headers,
    )
    assert created.status_code == 200
    run = client.post(
        f"/api/workflows/{created.json()['id']}/run",
        headers=headers,
    )
    assert run.status_code == 400
    assert "Connect" in run.json()["detail"] or "connect" in run.json()["detail"].lower()


def test_developer_cannot_run_workflow(client, developer, org_with_project):
    headers = {"Authorization": f"Bearer {developer['token']}"}
    project_id = org_with_project["project"]["id"]
    created = client.post(
        f"/api/workflows?project_id={project_id}",
        json={"name": "Blocked run", "skills": ["cloud_posture"], "enabled": True},
        headers=headers,
    )
    run = client.post(
        f"/api/workflows/{created.json()['id']}/run",
        headers=headers,
    )
    assert run.status_code == 403


def test_org_create_requires_super_admin(client, developer, super_admin):
    denied = client.post(
        "/api/orgs",
        json={"name": "Nope"},
        headers={"Authorization": f"Bearer {developer['token']}"},
    )
    assert denied.status_code == 403
    allowed = client.post(
        "/api/orgs",
        json={"name": "NewCo"},
        headers={"Authorization": f"Bearer {super_admin['token']}"},
    )
    assert allowed.status_code == 200
    assert allowed.json()["name"] == "NewCo"


def test_smtp_status_requires_org_admin(client, developer, org_admin):
    denied = client.get(
        "/api/smtp/status",
        headers={"Authorization": f"Bearer {developer['token']}"},
    )
    assert denied.status_code == 403
    allowed = client.get(
        "/api/smtp/status",
        headers={"Authorization": f"Bearer {org_admin['token']}"},
    )
    assert allowed.status_code == 200
    assert "configured" in allowed.json()
