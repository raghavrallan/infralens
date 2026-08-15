"""API coverage for remaining main/routes_mvp error and success branches."""
from __future__ import annotations

from unittest.mock import patch

import pytest

from app.execution import service as execution
from app.intelligence import workflows as intel
from app.platform import break_glass, connections, delivery


pytestmark = pytest.mark.integration


def _headers(user: dict) -> dict[str, str]:
    return {"Authorization": f"Bearer {user['token']}"}


def _connect(project_id: str) -> None:
    connections.set_connection(
        project_id,
        "azure",
        "client_secret",
        {
            "tenant_id": "t",
            "client_id": "c",
            "client_secret": "s",
            "subscription_id": "sub",
        },
    )


def test_action_approve_reject_and_missing(client, org_with_project):
    headers = _headers(org_with_project["admin"])
    project_id = org_with_project["project"]["id"]
    _connect(project_id)
    action = execution.create_action(
        project_id=project_id,
        provider="azure",
        executable="az",
        args=["group", "create", "--name", "demo", "--location", "eastus", "--output", "json"],
        target="rg/demo",
        access_scope="write",
        expected_result="resource group exists",
        risk="creates a resource group",
        rollback="az group delete --name demo --yes",
        preflight=["group", "show", "--name", "demo", "--output", "json"],
        verify=["group", "show", "--name", "demo", "--output", "json"],
    )
    missing = client.post(
        "/api/actions/missing/approve",
        json={"approver": "lead"},
        headers=headers,
    )
    assert missing.status_code == 404
    bad_state = client.post(
        f"/api/actions/{action['id']}/cancel",
        json={"approver": "lead"},
        headers=headers,
    )
    assert bad_state.status_code in {400, 409}
    rejected = client.post(
        f"/api/actions/{action['id']}/reject",
        json={"approver": "lead", "reason": "not now"},
        headers=headers,
    )
    assert rejected.status_code == 200
    already = client.post(
        f"/api/actions/{action['id']}/approve",
        json={"approver": "lead"},
        headers=headers,
    )
    assert already.status_code == 400
    missing_reject = client.post(
        "/api/actions/missing/reject",
        json={"approver": "lead", "reason": "x"},
        headers=headers,
    )
    assert missing_reject.status_code == 404


def test_break_glass_and_delivery_api(client, org_with_project):
    headers = _headers(org_with_project["admin"])
    project_id = org_with_project["project"]["id"]
    opened = client.post(
        "/api/break-glass/open",
        json={"project_id": project_id, "reason": "incident window for tests"},
        headers=headers,
    )
    assert opened.status_code in {200, 400}
    status = client.get("/api/break-glass/status", params={"project_id": project_id}, headers=headers)
    assert status.status_code == 200
    expired = client.post(
        "/api/break-glass/expire",
        params={"project_id": project_id},
        headers=headers,
    )
    assert expired.status_code == 200
    created = client.post(
        "/api/delivery/runs",
        json={"project_id": project_id},
        headers=headers,
    )
    assert created.status_code == 200
    run_id = created.json()["id"]
    listed = client.get("/api/delivery/runs", params={"project_id": project_id}, headers=headers)
    assert listed.status_code == 200
    fetched = client.get(f"/api/delivery/runs/{run_id}", headers=headers)
    assert fetched.status_code == 200
    ingest = client.post(
        f"/api/delivery/runs/{run_id}/docs",
        json={"docs": "# need an API"},
        headers=headers,
    )
    assert ingest.status_code in {200, 404, 422}
    moved = client.post(
        f"/api/delivery/runs/{run_id}/transition",
        json={"to_stage": "architecture"},
        headers=headers,
    )
    assert moved.status_code in {200, 400, 403}
    skip = client.post(
        f"/api/delivery/runs/{run_id}/transition",
        json={"to_stage": "apply"},
        headers=headers,
    )
    assert skip.status_code in {400, 403}
    missing_run = client.post(
        "/api/delivery/runs/missing/transition",
        json={"to_stage": "architecture"},
        headers=headers,
    )
    assert missing_run.status_code == 404
    unknown = client.post(
        f"/api/delivery/runs/{run_id}/transition",
        json={"to_stage": "moon"},
        headers=headers,
    )
    assert unknown.status_code == 400


def test_member_request_api_and_email_decide(client, org_with_project, devops_lead, developer):
    from app.tenancy import memberships

    headers = _headers(org_with_project["admin"])
    org_id = org_with_project["org"]["id"]
    project_id = org_with_project["project"]["id"]
    memberships.ensure_org_membership(org_id=org_id, user_id=devops_lead["id"], org_role="member")
    memberships.ensure_project_membership(
        project_id=project_id, user_id=devops_lead["id"], project_role="devops_lead"
    )
    lead_headers = _headers(devops_lead)
    with patch("app.tenancy.membership_requests.mailer.send_membership_request_email"):
        created = client.post(
            f"/api/projects/{project_id}/member-requests",
            json={
                "action": "add",
                "target_email": developer["email"],
                "project_role": "developer",
                "reason": "help",
            },
            headers=lead_headers,
        )
    assert created.status_code == 200
    request_id = created.json()["id"]
    token = created.json().get("approve_token") or ""
    listed = client.get(f"/api/orgs/{org_id}/member-requests", headers=headers)
    assert listed.status_code == 200
    bad = client.post(
        f"/api/member-requests/{request_id}/decide",
        json={"decision": "maybe"},
        headers=headers,
    )
    assert bad.status_code in {400, 422}
    if token:
        email = client.post(
            f"/api/member-requests/decide-email?request_id={request_id}",
            json={"decision": "rejected", "token": token},
        )
        assert email.status_code == 200
    missing_id = client.post(
        "/api/member-requests/decide-email",
        json={"decision": "rejected", "token": "x"},
    )
    assert missing_id.status_code == 400
    missing_token = client.post(
        f"/api/member-requests/decide-email?request_id={request_id}",
        json={"decision": "rejected"},
    )
    assert missing_token.status_code == 400
    invalid = client.post(
        f"/api/projects/{project_id}/member-requests",
        json={"action": "add"},
        headers=lead_headers,
    )
    assert invalid.status_code == 400


def test_workflow_run_enqueue_failure_and_approval_decide(client, org_with_project):
    headers = _headers(org_with_project["admin"])
    project_id = org_with_project["project"]["id"]
    _connect(project_id)
    intel.seed_default_workflows(project_id)
    workflows = intel.list_workflows(project_id)
    workflow_id = workflows[0]["id"]
    with patch("app.main.enqueue_run", side_effect=RuntimeError("redis down")):
        failed = client.post(f"/api/workflows/{workflow_id}/run", headers=headers)
    assert failed.status_code == 503
    missing_run = client.get("/api/runs/missing", headers=headers)
    assert missing_run.status_code == 404
    intel.save_findings(
        "run-api",
        workflow_id,
        project_id,
        [
            {
                "title": "Open SSH",
                "severity": "critical",
                "resource": "nsg-ssh",
                "skill": "cloud_posture",
                "recommended_action": "restrict",
                "gate_decision": "human_approval",
            }
        ],
    )
    approvals = intel.list_approvals(project_id)
    missing_approval = client.post(
        "/api/approvals/missing/decide",
        json={"decision": "approved"},
        headers=headers,
    )
    assert missing_approval.status_code == 404
    if approvals:
        decided = client.post(
            f"/api/approvals/{approvals[0]['id']}/decide",
            json={"decision": "approved"},
            headers=headers,
        )
        assert decided.status_code in {200, 403}


def test_frontend_pages_and_memory_precedent(client, org_with_project):
    headers = _headers(org_with_project["admin"])
    project_id = org_with_project["project"]["id"]
    for path in ("/", "/dashboard", "/settings", "/wiki", "/login", "/organizations"):
        response = client.get(path)
        assert response.status_code == 200
    chat_page = client.get("/c/demo-chat")
    assert chat_page.status_code == 200
    precedent = client.get(
        "/api/memory/precedent",
        params={"project_id": project_id},
        headers=headers,
    )
    assert precedent.status_code == 200
    _ = break_glass
    _ = delivery


def test_users_api_create_patch_and_forbidden(client, org_with_project, developer):
    headers = _headers(org_with_project["admin"])
    org_id = org_with_project["org"]["id"]
    listed = client.get("/api/users", params={"org_id": org_id}, headers=headers)
    assert listed.status_code == 200
    created = client.post(
        "/api/users",
        params={"org_id": org_id},
        json={"username": f"api_{org_id[:6]}", "password": "secret12", "role": "developer"},
        headers=headers,
    )
    assert created.status_code in {200, 400}
    if created.status_code == 200:
        user_id = created.json()["id"]
        patched = client.patch(
            f"/api/users/{user_id}",
            json={"display_name": "Patched", "is_active": True},
            headers=headers,
        )
        assert patched.status_code == 200
        missing = client.patch(
            "/api/users/missing",
            json={"display_name": "Nope"},
            headers=headers,
        )
        assert missing.status_code == 404
        duplicate = client.post(
            "/api/users",
            params={"org_id": org_id},
            json={"username": created.json()["username"], "password": "secret12"},
            headers=headers,
        )
        assert duplicate.status_code == 400
    forbidden = client.get("/api/users", headers=_headers(developer))
    assert forbidden.status_code == 403
    roles = client.get("/api/roles", headers=headers)
    assert roles.status_code == 200


def test_provider_and_onboarding_error_paths(client, org_with_project, developer):
    headers = _headers(org_with_project["admin"])
    project_id = org_with_project["project"]["id"]
    empty_pat = client.post(
        "/api/providers/github/pat",
        json={"project_id": project_id, "token": "   ", "username": "acme"},
        headers=headers,
    )
    assert empty_pat.status_code == 400
    missing_project = client.post(
        "/api/providers/github/pat",
        json={"project_id": "missing", "token": "ghp_abc", "username": "acme"},
        headers=headers,
    )
    assert missing_project.status_code == 404
    with patch("app.api.routes_mvp.onboarding.github_identity", side_effect=RuntimeError("bad token")):
        invalid = client.post(
            "/api/providers/github/pat",
            json={"project_id": project_id, "token": "ghp_abc", "username": "acme"},
            headers=headers,
        )
    assert invalid.status_code == 400
    azure_missing = client.post(
        "/api/providers/azure/secrets",
        json={
            "project_id": "missing",
            "tenant_id": "t",
            "client_id": "c",
            "client_secret": "s",
            "subscription_id": "sub",
        },
        headers=headers,
    )
    assert azure_missing.status_code == 404
    with patch("app.api.routes_mvp.onboarding.complete", side_effect=ValueError("need name")):
        onboard = client.post(
            "/api/onboarding/complete",
            json={"path": "new", "project_name": ""},
            headers=headers,
        )
    assert onboard.status_code == 400
    short_reason = client.post(
        "/api/break-glass/open",
        json={"project_id": project_id, "reason": "x"},
        headers=headers,
    )
    assert short_reason.status_code in {400, 422}
    ingest_missing = client.post(
        "/api/delivery/runs/missing/docs",
        json={"docs": "hi"},
        headers=headers,
    )
    assert ingest_missing.status_code == 404
    create_missing = client.post(
        "/api/delivery/runs",
        json={"project_id": "missing"},
        headers=headers,
    )
    assert create_missing.status_code in {403, 404}
    options = client.get("/api/providers/auth-options", headers=headers)
    assert options.status_code == 200
    patch_bad = client.patch(
        f"/api/users/{developer['id']}",
        json={"password": "x"},
        headers=headers,
    )
    assert patch_bad.status_code in {400, 403, 422}
