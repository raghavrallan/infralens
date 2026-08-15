"""Orchestrator run_chat with mocked providers and LLM."""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from app.chat.orchestrator import ChatTurn, run_chat
from app.chat.project_context import detect_project_mode
from app.platform import oauth_providers
from app.skills.base import Skill


@pytest.mark.unit
def test_detect_project_mode_fresh_vs_existing():
    with patch("app.chat.project_context.projects.get_repos", return_value=["acme/app"]):
        assert detect_project_mode("p1") == "existing"
    with patch("app.chat.project_context.projects.get_repos", return_value=[]):
        with patch("app.chat.project_context.github_infra.is_connected", return_value=False):
            with patch("app.chat.project_context.azure_infra.is_connected", return_value=False):
                with patch("app.chat.project_context.aws_infra.is_connected", return_value=False):
                    assert detect_project_mode("p1") == "fresh"


@pytest.mark.unit
def test_run_chat_forced_skill(monkeypatch):
    from app.chat.orchestrator import ChatTurn

    messages = [{"role": "user", "content": "write a report"}]
    expected = ChatTurn(mode="agent", reply="done", skills_used=["report_writer"])
    with patch("app.chat.orchestrator.registry.get", return_value=Skill()):
        with patch("app.chat.orchestrator._is_agentic", return_value=False):
            with patch("app.chat.orchestrator._gather_project_topology", return_value="topo"):
                with patch(
                    "app.chat.orchestrator._gather_live_context",
                    return_value=("live", []),
                ):
                    with patch(
                        "app.chat.orchestrator.provider_status_text",
                        return_value="status",
                    ):
                        with patch(
                            "app.chat.orchestrator._run_single_skill",
                            return_value=expected,
                        ):
                            turn = run_chat(messages, "p1", skill="report_writer")
    assert turn.reply == "done"
    assert "report_writer" in turn.skills_used


@pytest.mark.unit
def test_github_oauth_start_when_configured(monkeypatch):
    monkeypatch.setenv("GITHUB_OAUTH_CLIENT_ID", "id")
    monkeypatch.setenv("GITHUB_OAUTH_CLIENT_SECRET", "secret")
    monkeypatch.setenv("OAUTH_REDIRECT_BASE", "http://api.test")
    result = oauth_providers.start_github_oauth(
        project_id="p1", request_base="http://localhost:8000"
    )
    assert "github.com/login/oauth/authorize" in result["authorize_url"]
    assert result["state"]
    assert result["redirect_uri"].endswith("/api/providers/github/oauth/callback")


@pytest.mark.unit
def test_github_oauth_finish_success(monkeypatch):
    monkeypatch.setenv("GITHUB_OAUTH_CLIENT_ID", "id")
    monkeypatch.setenv("GITHUB_OAUTH_CLIENT_SECRET", "secret")
    started = oauth_providers.start_github_oauth(
        project_id="p1", request_base="http://api.test"
    )
    token_resp = MagicMock()
    token_resp.raise_for_status.return_value = None
    token_resp.json.return_value = {"access_token": "gho_x"}
    user_resp = MagicMock()
    user_resp.raise_for_status.return_value = None
    user_resp.json.return_value = {"login": "octocat"}
    client = MagicMock()
    client.__enter__.return_value = client
    client.__exit__.return_value = False
    client.post.return_value = token_resp
    client.get.return_value = user_resp
    with patch("app.platform.oauth_providers.httpx.Client", return_value=client):
        with patch(
            "app.platform.oauth_providers.connections.set_connection",
            return_value={"provider": "github", "connected": True},
        ):
            finished = oauth_providers.finish_github_oauth(
                code="abc",
                state=started["state"],
                request_base="http://api.test",
            )
    assert finished["identity"] == "octocat"
    assert "gho_x" not in str(finished)
