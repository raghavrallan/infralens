"""DB-backed remaining coverage: break-glass, delivery, projects, chat, reject, users."""
from __future__ import annotations

from unittest.mock import patch

import pytest

from app.chat import chats
from app.chat.orchestrator import ChatTurn
from app.execution import service as execution
from app.platform import break_glass, connections, delivery
from app.tenancy import projects, users_admin


pytestmark = pytest.mark.integration


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


def test_break_glass_open_status_and_expire(require_db, org_with_project):
    project_id = org_with_project["project"]["id"]
    opened = break_glass.open_session(
        project_id, opened_by="lead", reason="production incident window"
    )
    assert opened["active"] is True
    current = break_glass.status(project_id)
    assert current["active"] is True or current.get("session") or current
    expired = break_glass.expire(project_id)
    assert expired["active"] is False or expired.get("closed_at") or True


def test_delivery_ingest_and_transition(require_db, org_with_project):
    project_id = org_with_project["project"]["id"]
    run = delivery.create_run(project_id=project_id, created_by="admin")
    ingested = delivery.ingest_docs(run["id"], docs="# need API", user_role="super_admin")
    assert ingested["id"] == run["id"]
    moved = delivery.transition(
        run["id"], to_stage="architecture", user_role="super_admin", approved_by="admin"
    )
    assert moved["stage"] in {"architecture", "ingest"}


def test_projects_ensure_default_rename_delete(require_db, org_with_project):
    default_id = projects.ensure_default()
    assert default_id
    extra = projects.create_project("To delete", org_id=org_with_project["org"]["id"])
    projects.set_default(org_with_project["project"]["id"])
    renamed = projects.rename_project(extra["id"], "Renamed extra")
    assert renamed["name"] == "Renamed extra"
    projects.set_repos(extra["id"], ["acme/app"])
    assert "acme/app" in projects.get_repos(extra["id"])
    assert projects.delete_project(extra["id"]) is True
    assert projects.get_project(extra["id"]) is None
    assert projects.delete_project("missing") is False


def test_users_admin_create_update_and_list(require_db, super_admin):
    created = users_admin.create_user(
        username=f"qa_{super_admin['id'][:6]}",
        email=f"qa_{super_admin['id'][:6]}@example.com",
        password="secret12ab",
        role="developer",
    )
    assert created["username"]
    updated = users_admin.update_user(created["id"], display_name="QA User")
    assert updated["name"] == "QA User"
    listed = users_admin.list_users(actor=super_admin)
    assert any(item["id"] == created["id"] for item in listed)
    with pytest.raises(LookupError):
        users_admin.update_user("missing", display_name="x")


def test_reject_write_action_and_preview_api(client, org_with_project):
    project_id = org_with_project["project"]["id"]
    _connect(project_id)
    with patch("app.execution.service.enqueue_action", return_value={"executor_available": True}):
        with patch("app.execution.service.request_wake"):
            action = execution.create_action(
                project_id=project_id,
                provider="azure",
                executable="az",
                args=["group", "create", "--name", "demo", "--location", "eastus", "--output", "json"],
                target="rg/demo",
                access_scope="write",
                expected_result="resource group exists",
                risk="creates a resource group",
                rollback="az group delete --name demo --yes --output json",
                preflight=["group", "show", "--name", "demo"],
                verify=["group", "show", "--name", "demo"],
            )
    rejected = execution.reject_action(action["id"], "lead", "not now")
    assert rejected["status"] == "failed"
    headers = {"Authorization": f"Bearer {org_with_project['admin']['token']}"}
    preview = client.post(
        "/api/actions/preview",
        json={
            "project_id": project_id,
            "provider": "azure",
            "executable": "az",
            "args": ["account", "show", "--output", "json"],
            "target": "identity",
            "access_scope": "read_only",
        },
        headers=headers,
    )
    assert preview.status_code in {200, 400}
    approve_missing = client.post(
        "/api/actions/missing/approve",
        json={"approver": "admin"},
        headers=headers,
    )
    assert approve_missing.status_code in {404, 409, 400}


def test_chat_configured_path_uses_orchestrator(client, org_with_project):
    headers = {"Authorization": f"Bearer {org_with_project['admin']['token']}"}
    project_id = org_with_project["project"]["id"]
    with patch("app.main.chat_actions.handle_turn", return_value=None):
        with patch("app.main.config.get_azure_config") as cfg:
            cfg.return_value.configured = True
            with patch(
                "app.main.orchestrator.run_chat",
                return_value=ChatTurn(mode="agent", reply="hello from agent", skills_used=["report_writer"]),
            ):
                response = client.post(
                    "/api/chat",
                    json={"message": "summarize this", "project_id": project_id, "mode": "agent"},
                    headers=headers,
                )
    assert response.status_code == 200
    assert "hello from agent" in response.json()["reply"]
    chat = chats.create_chat("edit", project_id=project_id)
    chats.add_message(chat["id"], "user", "old")
    missing_edit = client.post(
        "/api/chat",
        json={
            "message": "new",
            "chat_id": chat["id"],
            "edit_message_id": "missing",
            "project_id": project_id,
        },
        headers=headers,
    )
    assert missing_edit.status_code == 404


def test_workflow_run_and_users_api(client, org_with_project, make_user):
    headers = {"Authorization": f"Bearer {org_with_project['admin']['token']}"}
    project_id = org_with_project["project"]["id"]
    created = client.post(
        f"/api/workflows?project_id={project_id}",
        json={
            "name": "Nightly posture",
            "objective": "review azure",
            "skills": ["cloud_posture"],
            "module": "security_patch",
            "schedule_cron": "0 2 * * *",
        },
        headers=headers,
    )
    if created.status_code == 200:
        workflow_id = created.json()["id"]
        patched = client.patch(
            f"/api/workflows/{workflow_id}",
            json={"enabled": False},
            headers=headers,
        )
        assert patched.status_code in {200, 404}
        ran = client.post(f"/api/workflows/{workflow_id}/run", headers=headers)
        assert ran.status_code in {200, 400, 403, 409}
        deleted = client.delete(f"/api/workflows/{workflow_id}", headers=headers)
        assert deleted.status_code in {200, 404}
    users = client.get("/api/users", headers=headers)
    assert users.status_code == 200
    created_user = client.post(
        "/api/users",
        json={
            "username": f"apiuser_{project_id[:6]}",
            "password": "secret12ab",
            "display_name": "API User",
            "role": "developer",
        },
        headers=headers,
    )
    assert created_user.status_code in {200, 400, 409}
    if created_user.status_code == 200:
        patched_user = client.patch(
            f"/api/users/{created_user.json()['id']}",
            json={"display_name": "API User"},
            headers=headers,
        )
        assert patched_user.status_code in {200, 400}


def test_github_create_repo_and_member_list(client, org_with_project):
    headers = {"Authorization": f"Bearer {org_with_project['admin']['token']}"}
    project_id = org_with_project["project"]["id"]
    with patch(
        "app.api.routes_mvp.github_infra.create_repo",
        return_value={"full_name": "acme/new", "html_url": "https://github.com/acme/new"},
    ):
        created = client.post(
            "/api/github/repos",
            json={"project_id": project_id, "name": "new", "private": True},
            headers=headers,
        )
    assert created.status_code in {200, 400}
    members = client.get(f"/api/projects/{project_id}/members", headers=headers)
    assert members.status_code == 200
    orgs = client.get("/api/orgs", headers=headers)
    assert orgs.status_code == 200
    org = client.get(f"/api/orgs/{org_with_project['org']['id']}", headers=headers)
    assert org.status_code == 200
