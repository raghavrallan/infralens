"""Azure logs report happy path, topology edges, and streaming chat special-action coverage."""
from __future__ import annotations

from unittest.mock import patch

import pytest

from app.providers import azure_infra
from app.providers.azure_infra import AzureCredentials


@pytest.mark.unit
def test_build_logs_report_with_revisions_and_postgres():
    creds = AzureCredentials("t", "c", "s", "sub")
    app = {
        "id": "/subscriptions/sub/resourceGroups/rg/providers/Microsoft.App/containerApps/demo",
        "name": "demo",
        "type": "microsoft.app/containerapps",
        "resourceGroup": "rg",
    }
    detail = {
        "properties": {
            "provisioningState": "Succeeded",
            "runningStatus": "Running",
            "latestRevisionName": "demo-1",
            "latestReadyRevisionName": "demo-1",
        }
    }
    revisions = {
        "value": [
            {
                "name": "demo-1",
                "properties": {
                    "createdTime": "2026-01-02T00:00:00Z",
                    "active": True,
                    "healthState": "Healthy",
                    "provisioningState": "Provisioned",
                    "runningState": "Running",
                    "replicas": 1,
                    "trafficWeight": 100,
                    "template": {"containers": [{"image": "demo:1"}]},
                },
            }
        ]
    }

    def _arm(_token, path, _api):
        if path.endswith("/revisions"):
            return revisions
        return detail

    with patch("app.providers.azure_infra.load_credentials", return_value=creds):
        with patch("app.providers.azure_infra._get_token", return_value="tok"):
            with patch("app.providers.azure_infra._log_workspaces", return_value=["ws-1"]):
                with patch("app.providers.azure_infra._get_logs_token", return_value="logs"):
                    with patch("app.providers.azure_infra._discover_resources", return_value=[app]):
                        with patch("app.providers.azure_infra._select_resources", return_value=[app]):
                            with patch("app.providers.azure_infra._arm_get", side_effect=_arm):
                                with patch(
                                    "app.providers.azure_infra._run_log_query",
                                    return_value=(["Reason_s", "n"], [["Probe", 2]]),
                                ):
                                    report = azure_infra.build_logs_report(
                                        "p1",
                                        "show postgres database errors in my container app logs",
                                        resource_name="demo",
                                    )
    assert "LIVE AZURE LOGS" in report["text"]
    assert "PostgreSQL" in report["text"]
    with patch("app.providers.azure_infra.load_credentials", return_value=creds):
        with patch("app.providers.azure_infra._get_token", return_value="tok"):
            with patch("app.providers.azure_infra._log_workspaces", return_value=[]):
                with patch(
                    "app.providers.azure_infra._run_query",
                    return_value=[{"cid": "fallback-ws"}],
                ):
                    with patch("app.providers.azure_infra._get_logs_token", return_value="logs"):
                        with patch("app.providers.azure_infra._discover_resources", return_value=[]):
                            with patch("app.providers.azure_infra._select_resources", return_value=[]):
                                with patch(
                                    "app.providers.azure_infra._run_log_query",
                                    return_value=([], []),
                                ):
                                    fallback = azure_infra.build_logs_report("p1", "show logs")
    assert "LIVE AZURE LOGS" in fallback["text"]


@pytest.mark.unit
def test_discover_topology_with_relationships():
    creds = AzureCredentials("t", "c", "s", "sub")
    inventory = [
        {
            "name": "app",
            "type": "microsoft.app/containerapps",
            "resourceGroup": "rg",
            "vnet": "/subscriptions/sub/resourceGroups/rg/providers/Microsoft.Network/virtualNetworks/vnet1",
            "subnet": "null",
            "nsg": "",
        }
    ]
    with patch("app.providers.azure_infra.load_credentials", return_value=creds):
        with patch("app.providers.azure_infra._get_token", return_value="tok"):
            with patch("app.providers.azure_infra._run_query", return_value=inventory):
                topo = azure_infra.discover_topology("p1")
    assert topo["resource_count"] == 1
    assert topo["relationships"]


@pytest.mark.integration
def test_chat_stream_special_action_and_unknown_skill(client, org_with_project):
    headers = {"Authorization": f"Bearer {org_with_project['admin']['token']}"}
    project_id = org_with_project["project"]["id"]
    unknown = client.post(
        "/api/chat/stream",
        json={"message": "hi", "skill": "nope", "project_id": project_id},
        headers=headers,
    )
    assert unknown.status_code == 400
    with patch(
        "app.main.chat_actions.handle_turn",
        return_value={
            "reply": "streamed action",
            "action": {"id": "s1", "status": "queued"},
            "event_type": "action_queued",
        },
    ):
        streamed = client.post(
            "/api/chat/stream",
            json={"message": "create rg", "mode": "agent", "project_id": project_id},
            headers=headers,
        )
    assert streamed.status_code == 200
    assert "streamed action" in streamed.text or "final" in streamed.text
    with patch("app.main.chat_actions.handle_turn", side_effect=ValueError("bad")):
        failed = client.post(
            "/api/chat/stream",
            json={"message": "create rg", "mode": "agent", "project_id": project_id},
            headers=headers,
        )
    assert failed.status_code == 200
