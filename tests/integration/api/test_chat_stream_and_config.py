"""Chat stream/execute-plan, Azure config, project mutation, and remaining main routes."""
from __future__ import annotations

from unittest.mock import patch

import pytest

from app.chat import chats


pytestmark = pytest.mark.integration


def _headers(org_with_project) -> dict[str, str]:
    return {"Authorization": f"Bearer {org_with_project['admin']['token']}"}


def test_chat_stream_special_action_and_unconfigured(client, org_with_project):
    headers = _headers(org_with_project)
    project_id = org_with_project["project"]["id"]
    special = {
        "reply": "Prepared Azure resource group `demo`.",
        "action": {
            "id": "act-1",
            "status": "awaiting_approval",
            "command_preview": "az group create",
        },
        "event_type": "approval_required",
        "required_action_scope": "write",
    }
    with patch("app.main.chat_actions.handle_turn", return_value=special):
        streamed = client.post(
            "/api/chat/stream",
            json={"message": "create resource group demo", "project_id": project_id},
            headers=headers,
        )
    assert streamed.status_code == 200
    assert "act-1" in streamed.text or "Prepared" in streamed.text
    with patch("app.main.chat_actions.handle_turn", return_value=None):
        with patch("app.main.config.get_azure_config") as cfg:
            cfg.return_value.configured = False
            offline = client.post(
                "/api/chat/stream",
                json={"message": "hello", "project_id": project_id, "mode": "plan"},
                headers=headers,
            )
    assert offline.status_code == 200
    assert "not configured" in offline.text.lower()


def test_chat_stream_orchestrator_events(client, org_with_project):
    headers = _headers(org_with_project)
    project_id = org_with_project["project"]["id"]
    with patch("app.main.chat_actions.handle_turn", return_value=None):
        with patch("app.main.config.get_azure_config") as cfg:
            cfg.return_value.configured = True
            with patch(
                "app.main.orchestrator.run_chat_stream",
                return_value=iter(
                    [
                        {"type": "status", "text": "Planning"},
                        {"type": "delta", "text": "hello "},
                        {"type": "final", "mode": "agent", "reply": "hello world", "skills_used": []},
                    ]
                ),
            ):
                response = client.post(
                    "/api/chat/stream",
                    json={"message": "hi there", "project_id": project_id},
                    headers=headers,
                )
    assert response.status_code == 200
    assert "hello" in response.text
    with patch("app.main.chat_actions.handle_turn", return_value=None):
        with patch("app.main.config.get_azure_config") as cfg:
            cfg.return_value.configured = True
            with patch(
                "app.main.orchestrator.run_chat_stream",
                side_effect=RuntimeError("model down"),
            ):
                failed = client.post(
                    "/api/chat/stream",
                    json={"message": "hi again", "project_id": project_id},
                    headers=headers,
                )
    assert failed.status_code == 200
    assert "failed" in failed.text.lower() or "model down" in failed.text


def test_execute_plan_stream_when_configured(client, org_with_project):
    headers = _headers(org_with_project)
    project_id = org_with_project["project"]["id"]
    chat = chats.create_chat("plan", project_id=project_id)
    with patch("app.main.config.get_azure_config") as cfg:
        cfg.return_value.configured = True
        with patch(
            "app.main.orchestrator.execute_plan_stream",
            return_value=iter(
                [
                    {"type": "status", "text": "Executing"},
                    {"type": "final", "mode": "agent", "reply": "done", "skills_used": ["report_writer"]},
                ]
            ),
        ):
            response = client.post(
                "/api/chat/execute-plan",
                json={
                    "chat_id": chat["id"],
                    "project_id": project_id,
                    "steps": [{"skill": "report_writer", "objective": "write"}],
                },
                headers=headers,
            )
    assert response.status_code == 200
    assert "done" in response.text


def test_chat_nonstream_special_action(client, org_with_project):
    headers = _headers(org_with_project)
    project_id = org_with_project["project"]["id"]
    with patch(
        "app.main.chat_actions.handle_turn",
        return_value={"reply": "queued", "action": {"id": "a1", "status": "queued"}},
    ):
        response = client.post(
            "/api/chat",
            json={"message": "yes", "project_id": project_id},
            headers=headers,
        )
    assert response.status_code == 200
    assert response.json()["action_id"] == "a1"


def test_azure_config_put_requires_super_admin(client, developer, org_with_project):
    denied = client.put(
        "/api/config/azure-openai",
        json={"endpoint": "https://example.openai.azure.com", "api_key": "k"},
        headers={"Authorization": f"Bearer {developer['token']}"},
    )
    assert denied.status_code == 403
    with patch("app.main.config.set_azure_config"):
        with patch("app.main.config.get_azure_config") as cfg:
            cfg.return_value.endpoint = "https://example.openai.azure.com"
            cfg.return_value.deployment = "gpt-4o"
            cfg.return_value.api_version = "2024-10-21"
            cfg.return_value.configured = True
            cfg.return_value.api_key = "k"
            allowed = client.put(
                "/api/config/azure-openai",
                json={"endpoint": "https://example.openai.azure.com", "api_key": "k"},
                headers=_headers(org_with_project),
            )
    assert allowed.status_code == 200
    assert allowed.json()["configured"] is True


def test_project_rename_default_and_delete(client, org_with_project):
    headers = _headers(org_with_project)
    project_id = org_with_project["project"]["id"]
    renamed = client.patch(
        f"/api/projects/{project_id}",
        json={"name": "Renamed project"},
        headers=headers,
    )
    assert renamed.status_code == 200
    assert renamed.json()["name"] == "Renamed project"
    defaulted = client.put(f"/api/projects/{project_id}/default", headers=headers)
    assert defaulted.status_code == 200
    blocked = client.delete(f"/api/projects/{project_id}", headers=headers)
    assert blocked.status_code == 400
    missing = client.patch(
        "/api/projects/missing",
        json={"name": "x"},
        headers=headers,
    )
    assert missing.status_code in {403, 404}


def test_approvals_and_architecture_runs(client, org_with_project):
    headers = _headers(org_with_project)
    project_id = org_with_project["project"]["id"]
    approvals = client.get(f"/api/approvals?project_id={project_id}", headers=headers)
    assert approvals.status_code == 200
    missing = client.post(
        "/api/approvals/missing/decide",
        json={"decision": "approved"},
        headers=headers,
    )
    assert missing.status_code == 404
    runs = client.get(f"/api/architecture/runs?project_id={project_id}", headers=headers)
    assert runs.status_code == 200
