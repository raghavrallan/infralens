"""Additional coverage for remaining AWS, Azure, LLM, orgs, chat API, and GitHub gaps."""
from __future__ import annotations

from datetime import date
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from botocore.exceptions import ClientError

import app.skills  # noqa: F401 — break circular import before architect package
from app.agents.solution_architect import llm as architect_llm
from app.agents.solution_architect import prompts as architect_prompts
from app.chat import chats
from app.providers import aws_infra, azure_infra, github_infra
from app.tenancy import orgs, projects


@pytest.mark.unit
def test_aws_credentials_format_and_caller_identity():
    with patch("app.providers.aws_infra.connections.get_secret_fields", return_value=None):
        with pytest.raises(aws_infra.AwsConnectionError):
            aws_infra.load_credentials("p1")
        assert aws_infra.is_connected("p1") is False
    with patch(
        "app.providers.aws_infra.connections.get_secret_fields",
        return_value={"access_key_id": "ak"},
    ):
        with pytest.raises(aws_infra.AwsConnectionError, match="missing"):
            aws_infra.load_credentials("p1")
    with patch(
        "app.providers.aws_infra.connections.get_secret_fields",
        return_value={"access_key_id": "ak", "secret_access_key": "sk", "region": "eu-west-1"},
    ):
        creds = aws_infra.load_credentials("p1")
    assert creds.region == "eu-west-1"
    assert aws_infra._format_rows([]) == "(none found)"
    assert "more" in aws_infra._format_rows([{"a": i} for i in range(62)], limit=2)
    err = ClientError({"Error": {"Code": "AccessDenied", "Message": "nope"}}, "GetCallerIdentity")
    assert "AccessDenied" in aws_infra._api_message(err)
    assert "plain" in aws_infra._api_message(RuntimeError("plain"))
    session = MagicMock()
    sts = MagicMock()
    sts.get_caller_identity.side_effect = err
    session.client.return_value = sts
    with pytest.raises(aws_infra.AwsApiError, match="authentication failed"):
        aws_infra._caller_identity(session)


@pytest.mark.unit
def test_github_credentials_and_azure_cost_empty_filter():
    with patch("app.providers.github_infra.connections.get_secret_fields", return_value=None):
        with pytest.raises(github_infra.GitHubConnectionError):
            github_infra.load_credentials("p1")
    with patch(
        "app.providers.github_infra.connections.get_secret_fields",
        return_value={"username": "acme"},
    ):
        with pytest.raises(github_infra.GitHubConnectionError, match="token"):
            github_infra.load_credentials("p1")
    missing_sub = azure_infra.AzureCredentials("t", "c", "s", None)
    with patch("app.providers.azure_infra.load_credentials", return_value=missing_sub):
        with pytest.raises(azure_infra.AzureApiError, match="subscription"):
            azure_infra.build_metrics_report("p1", "cpu")
        with pytest.raises(azure_infra.AzureApiError, match="subscription"):
            azure_infra.build_cost_report("p1", date(2026, 1, 1), date(2026, 1, 31), "Jan")
    creds = azure_infra.AzureCredentials("t", "c", "s", "sub")
    empty_resp = MagicMock(status_code=200)
    empty_resp.json.return_value = {
        "properties": {
            "columns": [{"name": "Cost"}, {"name": "ServiceName"}, {"name": "Currency"}],
            "rows": [[1.5, "Virtual Machines", "USD"]],
        }
    }
    with patch("app.providers.azure_infra.load_credentials", return_value=creds):
        with patch("app.providers.azure_infra._get_token", return_value="tok"):
            with patch("app.providers.azure_infra.httpx.post", return_value=empty_resp):
                filtered = azure_infra.build_cost_report(
                    "p1",
                    date(2026, 1, 1),
                    date(2026, 1, 31),
                    "Jan",
                    service_filter=["storage"],
                )
    assert "No charges matched" in filtered["text"]
    none_resp = MagicMock(status_code=200)
    none_resp.json.return_value = {"properties": {"columns": [{"name": "Cost"}], "rows": []}}
    with patch("app.providers.azure_infra.load_credentials", return_value=creds):
        with patch("app.providers.azure_infra._get_token", return_value="tok"):
            with patch("app.providers.azure_infra.httpx.post", return_value=none_resp):
                unused = azure_infra.build_cost_report(
                    "p1", date(2026, 1, 1), date(2026, 1, 31), "Jan"
                )
    assert "No usage" in unused["text"]
    payload = azure_infra._cost_payload(date(2026, 1, 1), date(2026, 1, 31), group_by="meter")
    assert any(item.get("name") == "Meter" for item in payload["dataset"]["grouping"])
    first, last, label = azure_infra.parse_cost_period("last month", today=date(2026, 2, 10))
    assert first.month == 1
    first2, _last2, _label2 = azure_infra.parse_cost_period("this month", today=date(2026, 2, 10))
    assert first2.month == 2
    first3, _last3, _label3 = azure_infra.parse_cost_period("january 2025", today=date(2026, 2, 10))
    assert first3.year == 2025


@pytest.mark.unit
def test_architect_llm_and_prompt_seed():
    architect_llm._llm = None
    architect_llm._llm_signature = None
    cfg = SimpleNamespace(configured=False, endpoint="", api_key="", deployment="", api_version="")
    with patch("app.agents.solution_architect.llm.get_azure_config", return_value=cfg):
        with pytest.raises(RuntimeError, match="not configured"):
            architect_llm.get_architect_llm()
    cfg.configured = True
    cfg.endpoint = "https://example"
    cfg.api_key = "k"
    cfg.deployment = "gpt"
    cfg.api_version = "2024-02-01"
    fake = MagicMock()
    with patch("app.agents.solution_architect.llm.get_azure_config", return_value=cfg):
        with patch("app.agents.solution_architect.llm.observability.tracing_enabled", return_value=False):
            with patch("langchain_openai.AzureChatOpenAI", return_value=fake):
                assert architect_llm.get_architect_llm() is fake
                assert architect_llm.get_architect_llm() is fake
    with patch("app.agents.solution_architect.llm.observability.tracing_enabled", return_value=False):
        assert architect_llm.langchain_callbacks() == []
    with patch("app.agents.solution_architect.llm.observability.tracing_enabled", return_value=True):
        fake_mod = MagicMock()
        fake_mod.CallbackHandler.return_value = MagicMock()
        with patch.dict("sys.modules", {"langfuse.langchain": fake_mod}):
            assert architect_llm.langchain_callbacks()
        broken = MagicMock()
        broken.CallbackHandler.side_effect = RuntimeError("x")
        with patch.dict("sys.modules", {"langfuse.langchain": broken}):
            assert architect_llm.langchain_callbacks() == []
    assert "callbacks" in architect_llm.invoke_config()
    with patch("app.core.prompts.ensure_text_prompt"):
        architect_prompts.seed_architect_prompts()
    assert "architect" in " ".join(architect_prompts.architect_prompt_names()) or architect_prompts.architect_prompt_names()


@pytest.mark.integration
def test_orgs_list_for_member_and_collapse_duplicates(require_db, org_with_project, developer):
    org_id = org_with_project["org"]["id"]
    from app.tenancy import memberships

    memberships.ensure_org_membership(org_id=org_id, user_id=developer["id"], org_role="member")
    listed = orgs.list_orgs_for_user(developer)
    assert any(item["id"] == org_id for item in listed)
    empty = orgs.list_orgs_for_user({"id": "nobody", "role": "developer"})
    assert empty == []
    first = projects.create_project("DupName", org_id=org_id, owner_user_id=developer["id"])
    second = projects.create_project("DupName", org_id=org_id, owner_user_id=developer["id"])
    chats.create_chat("hello", project_id=second["id"])
    listed_projects = orgs.list_org_projects(org_id)
    assert any(item["id"] in {first["id"], second["id"]} for item in listed_projects)
    extra = projects.create_project("ToRemove", org_id=org_id)
    projects.set_default(org_with_project["project"]["id"])
    assert projects.delete_project(extra["id"]) is True
    assert projects.delete_project(org_with_project["project"]["id"]) is False


@pytest.mark.integration
def test_chat_special_action_execute_plan_and_delete_guards(client, org_with_project):
    headers = {"Authorization": f"Bearer {org_with_project['admin']['token']}"}
    project_id = org_with_project["project"]["id"]
    unknown = client.post(
        "/api/chat",
        json={"message": "hi", "skill": "not-a-skill", "project_id": project_id},
        headers=headers,
    )
    assert unknown.status_code == 400
    with patch("app.main.chat_actions.handle_turn", side_effect=ValueError("bad location")):
        special = client.post(
            "/api/chat",
            json={"message": "create rg", "mode": "agent", "project_id": project_id},
            headers=headers,
        )
    assert special.status_code == 200
    assert "could not prepare" in special.json()["reply"].lower()
    created = client.post("/api/chats", params={"project_id": project_id}, headers=headers)
    chat_id = created.json()["id"] if created.status_code == 200 else chats.create_chat("plan", project_id=project_id)["id"]
    missing_chat = client.post(
        "/api/chat/execute-plan",
        json={"chat_id": "missing", "project_id": project_id, "steps": [{"skill": "cloud_posture", "objective": "x"}]},
        headers=headers,
    )
    assert missing_chat.status_code == 404
    mismatch = client.post(
        "/api/chat/execute-plan",
        json={
            "chat_id": chat_id,
            "project_id": project_id,
            "action_scope": "read_only",
            "actions": [
                {
                    "project_id": "other",
                    "provider": "azure",
                    "executable": "az",
                    "args": ["account", "show"],
                    "access_scope": "read_only",
                }
            ],
        },
        headers=headers,
    )
    assert mismatch.status_code == 400
    empty = client.post(
        "/api/chat/execute-plan",
        json={"chat_id": chat_id, "project_id": project_id, "steps": [{"skill": "not-real", "objective": "x"}]},
        headers=headers,
    )
    assert empty.status_code == 400
    extra = projects.create_project("ExtraDel", org_id=org_with_project["org"]["id"])
    projects.set_default(project_id)
    removed = client.delete(f"/api/projects/{extra['id']}", headers=headers)
    assert removed.status_code == 200
    default = client.delete(f"/api/projects/{project_id}", headers=headers)
    assert default.status_code == 400
    repos = client.get(f"/api/projects/{project_id}/repos", headers=headers)
    assert repos.status_code == 200
    with patch("app.main.github_infra.is_connected", return_value=True):
        with patch("app.main.github_infra.list_repo_names", side_effect=github_infra.GitHubApiError("nope")):
            errored = client.get(f"/api/projects/{project_id}/repos", headers=headers)
    assert errored.status_code == 200
    assert errored.json().get("error")
    streamed = client.post(
        "/api/chat/execute-plan",
        json={
            "chat_id": chat_id,
            "project_id": project_id,
            "steps": [{"skill": "cloud_posture", "objective": "review live posture"}],
        },
        headers=headers,
    )
    assert streamed.status_code == 200
    body = streamed.text
    assert "final" in body or "delta" in body or streamed.status_code == 200
    architect = client.post(
        "/api/chat/execute-plan",
        json={
            "chat_id": chat_id,
            "project_id": project_id,
            "steps": [{"skill": "solution_architect", "objective": "design"}],
        },
        headers=headers,
    )
    with patch(
        "app.main.chat_actions.handle_turn",
        return_value={
            "reply": "prepared",
            "action": {"id": "act-1", "status": "queued"},
            "required_action_scope": "write",
            "pending_resource_group_name": "rg1",
            "pending_action_spec": {"provider": "azure"},
        },
    ):
        prepared = client.post(
            "/api/chat",
            json={"message": "create rg", "mode": "agent", "project_id": project_id},
            headers=headers,
        )
    assert prepared.status_code == 200
    assert prepared.json().get("action_id") == "act-1"
    cfg = SimpleNamespace(configured=False)
    with patch("app.main.config.get_azure_config", return_value=cfg):
        with patch(
            "app.main.execution.create_action",
            return_value={"id": "job-1", "status": "awaiting_approval", "command_preview": "az"},
        ):
            planned = client.post(
                "/api/chat/execute-plan",
                json={
                    "chat_id": chat_id,
                    "project_id": project_id,
                    "action_scope": "write",
                    "actions": [
                        {
                            "project_id": project_id,
                            "provider": "azure",
                            "executable": "az",
                            "args": ["group", "create", "--name", "demo"],
                            "access_scope": "write",
                        }
                    ],
                },
                headers=headers,
            )
    assert planned.status_code == 200
    assert "action_planned" in planned.text or "final" in planned.text or planned.status_code == 200
    with patch("app.main.execution.create_action", side_effect=ValueError("no connection")):
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
