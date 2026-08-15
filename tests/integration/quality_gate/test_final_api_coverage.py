"""Integration coverage for remaining API, auth seed, workflows, diagnose, and chat meta."""
from __future__ import annotations

from datetime import date, datetime, timezone
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import select

from app.core import auth
from app.core.db import (
    AppConfig,
    Approval,
    DELETED_PROJECTS_CONFIG_KEY,
    ExecutionJob,
    Finding,
    SessionLocal,
    User,
)
from app.execution import service as execution
from app.intelligence import workflows as intel
from app.platform import connections
from app.tenancy import memberships, projects


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


def test_org_create_invite_accept_and_member_decide_errors(
    client, org_with_project, super_admin, developer
):
    headers = _headers(super_admin)
    empty = client.post("/api/orgs", json={"name": "   "}, headers=headers)
    assert empty.status_code == 400
    created = client.post(
        "/api/orgs",
        json={"name": f"GateOrg-{super_admin['id'][:6]}", "slug": "gate-org"},
        headers=headers,
    )
    assert created.status_code == 200
    org_id = org_with_project["org"]["id"]
    invite = client.post(
        f"/api/orgs/{org_id}/invites",
        json={"email": "invitee@example.com", "invited_role": "developer"},
        headers=_headers(org_with_project["admin"]),
    )
    assert invite.status_code in {200, 201}
    token = invite.json().get("accept_token") or invite.json().get("token")
    if token:
        with patch(
            "app.api.routes_mvp.auth.authenticate",
            return_value={"token": "session", "user": {"username": "invitee"}},
        ):
            accepted = client.post(
                "/api/invites/accept",
                json={"token": token, "password": "secret12ab", "display_name": "Invitee"},
            )
        assert accepted.status_code in {200, 400}
        if accepted.status_code == 200:
            assert accepted.json().get("session") or accepted.json().get("username")
    missing_invite = client.post(
        "/api/invites/accept",
        json={"token": "missing", "password": "secret12ab"},
    )
    assert missing_invite.status_code in {400, 404}
    with patch(
        "app.api.routes_mvp.membership_requests.decide_request",
        side_effect=PermissionError("not admin"),
    ):
        forbidden = client.post(
            "/api/member-requests/req-1/decide",
            json={"decision": "approved"},
            headers=_headers(org_with_project["admin"]),
        )
    assert forbidden.status_code == 403
    with patch(
        "app.api.routes_mvp.membership_requests.decide_request",
        side_effect=LookupError("gone"),
    ):
        missing = client.post(
            "/api/member-requests/req-1/decide",
            json={"decision": "approved"},
            headers=_headers(org_with_project["admin"]),
        )
    assert missing.status_code == 404
    with patch(
        "app.api.routes_mvp.membership_requests.decide_request",
        side_effect=ValueError("already decided"),
    ):
        invalid = client.post(
            "/api/member-requests/req-1/decide",
            json={"decision": "approved"},
            headers=_headers(org_with_project["admin"]),
        )
    assert invalid.status_code == 400
    memberships.ensure_org_membership(
        org_id=org_id, user_id=developer["id"], org_role="org_admin"
    )
    listed = client.get("/api/users", headers=_headers(developer))
    assert listed.status_code == 200


def test_chat_agent_success_meta_and_execute_plan_stream(client, org_with_project):
    headers = _headers(org_with_project["admin"])
    project_id = org_with_project["project"]["id"]
    created = client.post("/api/chats", params={"project_id": project_id}, headers=headers)
    chat_id = created.json()["id"]
    special = {
        "reply": "queued rg",
        "action": {"id": "a1", "status": "queued"},
        "event_type": "action_queued",
        "pending_resource_group_name": "testing",
        "pending_action_spec": {"provider": "azure"},
        "required_action_scope": "write",
    }
    with patch("app.main.chat_actions.handle_turn", return_value=special):
        agent = client.post(
            "/api/chat",
            json={
                "message": "create rg",
                "mode": "agent",
                "project_id": project_id,
                "chat_id": chat_id,
            },
            headers=headers,
        )
    assert agent.status_code == 200
    body = agent.json()
    assert body.get("action_id") == "a1" or body.get("action")
    assert body.get("required_action_scope") == "write"
    missing_edit = client.post(
        "/api/chat",
        json={
            "message": "edited",
            "project_id": project_id,
            "chat_id": chat_id,
            "edit_message_id": "missing",
        },
        headers=headers,
    )
    assert missing_edit.status_code == 404
    stream_edit = client.post(
        "/api/chat/stream",
        json={
            "message": "edited",
            "project_id": project_id,
            "chat_id": chat_id,
            "edit_message_id": "missing",
        },
        headers=headers,
    )
    assert stream_edit.status_code == 404
    with patch("app.main.config.get_azure_config", return_value=MagicMock(configured=True)):
        with patch(
            "app.main.chat_actions.action_diagnostic_context",
            return_value="diag",
        ):
            with patch(
                "app.main.orchestrator.execute_plan_stream",
                return_value=iter(
                    [
                        {"type": "delta", "text": "step"},
                        {
                            "type": "final",
                            "mode": "agent",
                            "reply": "done",
                            "skills_used": [],
                        },
                    ]
                ),
            ):
                streamed = client.post(
                    "/api/chat/execute-plan",
                    json={
                        "chat_id": chat_id,
                        "project_id": project_id,
                        "steps": [{"skill": "cloud_posture", "objective": "review"}],
                    },
                    headers=headers,
                )
    assert streamed.status_code == 200
    assert "done" in streamed.text or "final" in streamed.text
    _connect(project_id)
    with patch(
        "app.execution.service.enqueue_action",
        return_value={"executor_available": True, "queue": "q"},
    ):
        action = execution.create_action(
            project_id=project_id,
            provider="azure",
            executable="az",
            args=["group", "show", "--name", "demo", "--output", "json"],
            target="rg/demo",
            access_scope="read_only",
            expected_result="exists",
            risk="read",
            rollback="",
            preflight=[],
            verify=["group", "show", "--name", "demo", "--output", "json"],
        )
    with patch("app.main.execution.create_action", return_value=action):
        with patch("app.main.config.get_azure_config", return_value=MagicMock(configured=False)):
            queued = client.post(
                "/api/chat/execute-plan",
                json={
                    "chat_id": chat_id,
                    "project_id": project_id,
                    "action_scope": "read_only",
                    "actions": [
                        {
                            "project_id": project_id,
                            "provider": "azure",
                            "executable": "az",
                            "args": ["account", "show"],
                            "access_scope": "read_only",
                            "target": "identity",
                        }
                    ],
                },
                headers=headers,
            )
    assert queued.status_code == 200
    with patch("app.main.execution.create_action", side_effect=ValueError("bad action")):
        bad_action = client.post(
            "/api/chat/execute-plan",
            json={
                "chat_id": chat_id,
                "project_id": project_id,
                "action_scope": "read_only",
                "actions": [
                    {
                        "project_id": project_id,
                        "provider": "azure",
                        "executable": "az",
                        "args": ["account", "show"],
                        "access_scope": "read_only",
                    }
                ],
            },
            headers=headers,
        )
    assert bad_action.status_code == 400
    scope_mismatch = client.post(
        "/api/chat/execute-plan",
        json={
            "chat_id": chat_id,
            "project_id": project_id,
            "action_scope": "read_only",
            "actions": [
                {
                    "project_id": project_id,
                    "provider": "azure",
                    "executable": "az",
                    "args": ["account", "show"],
                    "access_scope": "write",
                }
            ],
        },
        headers=headers,
    )
    assert scope_mismatch.status_code == 400


def test_ensure_seed_user_promotes_existing_and_authenticate_inactive(require_db, make_user):
    seed_name = auth._seed_username()
    with SessionLocal() as session:
        row = session.scalar(select(User).where(User.username == seed_name))
        if row is not None:
            row.role = "developer"
            session.commit()
            user_id = row.id
        else:
            user_id = None
    if user_id:
        auth.ensure_seed_user()
        with SessionLocal() as session:
            refreshed = session.get(User, user_id)
        assert refreshed.role == "super_admin"
    inactive = make_user(is_active=False, password="secret12")
    assert auth.authenticate(inactive["username"], "secret12") is None
    assert auth.authenticate("", "secret12") is None
    assert auth.authenticate("nobody", "secret12") is None
    request = type("R", (), {"state": type("S", (), {"user": {}})()})()
    from fastapi import HTTPException

    with pytest.raises(HTTPException):
        auth.require_user(request, authorization="Bearer not-valid")


def test_projects_ensure_default_and_soft_delete_tombstone(require_db, org_with_project):
    extra = projects.create_project("SoftDel", org_id=org_with_project["org"]["id"])
    projects.set_default(org_with_project["project"]["id"])
    with patch("app.tenancy.projects._try_execute", return_value=False):
        assert projects.delete_project(extra["id"]) is True
    with SessionLocal() as session:
        setting = session.get(AppConfig, DELETED_PROJECTS_CONFIG_KEY)
    assert setting is not None
    assert extra["id"] in (setting.value or "")
    assert projects.delete_project(extra["id"]) is False
    assert projects.delete_project("missing") is False
    default_id = projects.ensure_default()
    assert default_id
    listed = projects.list_projects()
    assert listed


def test_workflows_decide_approval_missing_finding_and_dashboard_filters(
    require_db, org_with_project
):
    project_id = org_with_project["project"]["id"]
    intel.seed_default_workflows(project_id)
    workflows = intel.list_workflows(project_id)
    workflow_id = workflows[0]["id"]
    intel.save_findings(
        "run-gap",
        workflow_id,
        project_id,
        [
            {
                "title": "Open NSG",
                "severity": "high",
                "resource": "nsg-1",
                "skill": "cloud_posture",
                "recommended_action": "restrict",
                "gate_decision": "human_approval",
            }
        ],
    )
    approvals = intel.list_approvals(project_id)
    assert intel.decide_approval("missing", "approved") is None
    assert intel.decide_approval(approvals[0]["id"] if approvals else "x", "nope") is None
    if approvals:
        approval_id = approvals[0]["id"]
        with SessionLocal() as session:
            row = session.get(Approval, approval_id)
            finding_id = row.finding_id
            finding = session.get(Finding, finding_id)
            if finding is not None:
                session.delete(finding)
                session.commit()
        decided = intel.decide_approval(approval_id, "rejected")
        assert decided is not None
        assert decided["decision"] == "rejected"
    summary = intel.dashboard_summary(
        project_id,
        time_range="custom",
        module=workflows[0].get("module"),
        start_date=date(2020, 1, 1),
        end_date=date(2030, 1, 1),
    )
    assert summary


def test_diagnose_running_and_queued_with_executor(require_db, org_with_project):
    project_id = org_with_project["project"]["id"]
    _connect(project_id)
    with patch(
        "app.execution.service.enqueue_action",
        return_value={"executor_available": True, "queue": "q"},
    ):
        action = execution.create_action(
            project_id=project_id,
            provider="azure",
            executable="az",
            args=["account", "show"],
            target="identity",
            access_scope="read_only",
            expected_result="ok",
            risk="read",
            rollback="",
            preflight=[],
            verify=[],
        )
    with SessionLocal() as session:
        job = session.get(ExecutionJob, action["id"])
        job.status = "running"
        job.queued_at = datetime.now(timezone.utc)
        session.commit()
    with patch(
        "app.execution.service.queue_snapshot",
        return_value={"executor_available": True, "queue": "azure-ro", "queue_depth": 0},
    ):
        running = execution.diagnose_action(action["id"])
    assert "running" in running["message"].lower()
    with SessionLocal() as session:
        job = session.get(ExecutionJob, action["id"])
        job.status = "queued"
        session.commit()
    with patch(
        "app.execution.service.queue_snapshot",
        return_value={"executor_available": True, "queue": "azure-ro", "queue_depth": 1},
    ):
        waiting = execution.diagnose_action(action["id"])
    assert "waiting" in waiting["message"].lower()
    with patch(
        "app.execution.service.org_executor_settings.get_settings",
        return_value={"actual_state": "error", "in_warm_window": False, "mode": "on_demand"},
    ):
        with patch("app.execution.service.request_wake", side_effect=RuntimeError("wake down")):
            with patch(
                "app.execution.service.enqueue_action",
                return_value={"executor_available": False, "queue": "azure-ro"},
            ):
                dispatch = execution._dispatch_action(
                    action["id"], project_id, "azure", "read_only"
                )
    assert dispatch.get("executor_warming") is True


def test_chat_agent_falls_through_when_handle_turn_returns_none(client, org_with_project, developer):
    headers = _headers(org_with_project["admin"])
    project_id = org_with_project["project"]["id"]
    with patch("app.main.chat_actions.handle_turn", return_value=None):
        with patch("app.main.config.get_azure_config", return_value=MagicMock(configured=False)):
            with patch(
                "app.main.chat_actions.provider_status_text",
                return_value="providers",
            ):
                response = client.post(
                    "/api/chat",
                    json={"message": "hello", "mode": "agent", "project_id": project_id},
                    headers=headers,
                )
    assert response.status_code == 200
    assert "not configured" in response.json()["reply"].lower()
    with patch("app.main.config.get_azure_config", return_value=MagicMock(configured=True)):
        with patch(
            "app.main.orchestrator.execute_plan_stream",
            side_effect=RuntimeError("plan exploded"),
        ):
            created = client.post("/api/chats", params={"project_id": project_id}, headers=headers)
            chat_id = created.json()["id"]
            failed = client.post(
                "/api/chat/execute-plan",
                json={
                    "chat_id": chat_id,
                    "project_id": project_id,
                    "steps": [{"skill": "cloud_posture", "objective": "review"}],
                },
                headers=headers,
            )
    assert failed.status_code == 200
    assert "failed" in failed.text.lower() or "exploded" in failed.text.lower()
    other = client.post(
        "/api/orgs",
        json={"name": f"Other-{developer['id'][:6]}"},
        headers=_headers(org_with_project["admin"]),
    )
    if other.status_code == 200:
        memberships.ensure_org_membership(
            org_id=org_with_project["org"]["id"],
            user_id=developer["id"],
            org_role="org_admin",
        )
        listed = client.get(
            "/api/users",
            params={"org_id": other.json()["id"]},
            headers=_headers(developer),
        )
        assert listed.status_code in {200, 403}
    email_decide = client.post(
        "/api/member-requests/decide-email",
        json={"decision": "approved"},
    )
    assert email_decide.status_code == 400
    email_no_token = client.post(
        "/api/member-requests/decide-email?request_id=req-1",
        json={"decision": "approved"},
    )
    assert email_no_token.status_code == 400
    with patch(
        "app.api.routes_mvp.membership_requests.decide_request",
        side_effect=PermissionError("nope"),
    ):
        email_forbidden = client.post(
            "/api/member-requests/decide-email?request_id=req-1",
            json={"decision": "approved", "token": "tok"},
        )
    assert email_forbidden.status_code == 403
    no_org = client.post(
        "/api/users",
        json={"username": "x", "password": "secret12"},
        headers=_headers(developer),
    )
    assert no_org.status_code in {400, 403}
    auth.invalidate_user_cache()
    loaded = auth._load_user_from_db(org_with_project["admin"]["id"])
    assert loaded is not None
    cached = auth._load_user_from_db(org_with_project["admin"]["id"])
    assert cached["id"] == loaded["id"]
    assert auth._load_user_from_db("missing") is None
    with patch("app.core.auth.engine.begin", side_effect=RuntimeError("no column")):
        auth.ensure_seed_user()


def test_invite_expiry_users_admin_union_and_openai_not_configured(
    client, org_with_project, developer
):
    from datetime import timedelta

    from app.core.db import Invite
    from app.tenancy import invites, users_admin

    headers = _headers(org_with_project["admin"])
    org_id = org_with_project["org"]["id"]
    created = invites.create_invite(
        org_id=org_id,
        email="expiree@example.com",
        invited_by=org_with_project["admin"]["id"],
        invited_role="developer",
    )
    token = created.get("accept_token")
    if token:
        with SessionLocal() as session:
            row = session.scalar(
                select(Invite).where(Invite.email == "expiree@example.com")
            )
            if row is not None:
                row.expires_at = datetime.now(timezone.utc) - timedelta(days=1)
                session.commit()
        with pytest.raises(ValueError, match="expired"):
            invites.peek_invite(token)
    with pytest.raises(LookupError):
        invites.peek_invite("missing-token")
    with pytest.raises(ValueError, match="Password"):
        invites.accept_invite(token="x", password="ab")
    memberships.ensure_org_membership(
        org_id=org_id, user_id=developer["id"], org_role="member"
    )
    union = users_admin.list_users(actor=developer)
    assert union
    empty_org = users_admin.list_users(
        org_id=org_id, actor=org_with_project["admin"]
    )
    assert empty_org
    with pytest.raises(LookupError):
        users_admin.update_user("missing", display_name="x")
    project_id = org_with_project["project"]["id"]
    created_chat = client.post(
        "/api/chats", params={"project_id": project_id}, headers=headers
    )
    chat_id = created_chat.json()["id"]
    from app.core.azure_client import AzureOpenAINotConfiguredError

    with patch("app.main.config.get_azure_config", return_value=MagicMock(configured=True)):
        with patch(
            "app.main.orchestrator.execute_plan_stream",
            side_effect=AzureOpenAINotConfiguredError("no openai"),
        ):
            streamed = client.post(
                "/api/chat/execute-plan",
                json={
                    "chat_id": chat_id,
                    "project_id": project_id,
                    "steps": [{"skill": "cloud_posture", "objective": "review"}],
                },
                headers=headers,
            )
    assert streamed.status_code == 200
    with patch(
        "app.api.routes_mvp.membership_requests.decide_request",
        side_effect=LookupError("gone"),
    ):
        missing_email = client.post(
            "/api/member-requests/decide-email?request_id=req-1",
            json={"decision": "approved", "token": "tok"},
        )
    assert missing_email.status_code == 404
    with patch(
        "app.api.routes_mvp.membership_requests.decide_request",
        side_effect=ValueError("bad"),
    ):
        bad_email = client.post(
            "/api/member-requests/decide-email?request_id=req-1",
            json={"decision": "approved", "token": "tok"},
        )
    assert bad_email.status_code == 400

