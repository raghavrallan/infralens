"""Worker context filtering, scheduler lifecycle, chat titles, project topology."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from app.chat.chats import _title_from_text
from app.chat.project_context import ProjectContext
from app.intelligence import scheduler
from app.intelligence.worker import _usable_context, run_workflow
from app.providers import azure_infra
from app.providers.azure_infra import AzureCredentials


@pytest.mark.unit
def test_chat_title_truncation():
    assert _title_from_text("") == "New chat"
    assert _title_from_text("short") == "short"
    long = "x" * 80
    title = _title_from_text(long)
    assert title.endswith("…")
    assert len(title) <= 60


@pytest.mark.unit
def test_project_context_prompt_is_secret_free():
    ctx = ProjectContext(
        project_id="p1",
        mode="existing",
        project_name="Demo",
        repos=["acme/app"],
        providers={
            "azure": {"connected": True, "identity": "client-id"},
            "github": {"connected": True, "identity": "octo"},
            "aws": {"connected": False},
        },
        iac_files=[{"repo": "acme/app", "path": "infra/main.tf"}],
        app_structure={"backend": ["api"]},
        summary="ready",
    )
    text = ctx.to_prompt_text()
    assert "PROJECT TOPOLOGY" in text
    assert "acme/app" in text
    assert "secret" not in text.lower()
    dumped = ctx.to_dict()
    assert dumped["mode"] == "existing"


@pytest.mark.unit
def test_usable_context_drops_provider_failures():
    blob = (
        "LIVE AZURE FETCH FAILED. The user's azure account IS connected\n\n"
        "---\n\n"
        "LIVE AZURE ENVIRONMENT DATA — real resources here"
    )
    cleaned = _usable_context(blob)
    assert "ENVIRONMENT DATA" in cleaned
    assert "FETCH FAILED" not in cleaned


@pytest.mark.unit
def test_run_workflow_missing_run():
    with patch("app.intelligence.worker.init_db"):
        with patch("app.intelligence.worker.store.get_run", return_value=None):
            assert run_workflow("missing") == {"findings": 0}


@pytest.mark.unit
def test_run_workflow_missing_workflow():
    with patch("app.intelligence.worker.init_db"):
        with patch(
            "app.intelligence.worker.store.get_run",
            return_value={"workflow_id": "w1"},
        ):
            with patch("app.intelligence.worker.store.get_workflow", return_value=None):
                with patch("app.intelligence.worker.store.mark_run_failed") as failed:
                    assert run_workflow("r1") == {"findings": 0}
                    failed.assert_called()


@pytest.mark.unit
def test_scheduler_start_sync_and_shutdown():
    scheduler._scheduler = None
    fake = MagicMock()
    with patch("app.intelligence.scheduler.BackgroundScheduler", return_value=fake):
        with patch("app.intelligence.scheduler.sync_schedules"):
            scheduler.start_scheduler()
            scheduler.start_scheduler()  # idempotent
    fake.start.assert_called_once()
    scheduler.shutdown_scheduler()
    fake.shutdown.assert_called()
    assert scheduler._scheduler is None


@pytest.mark.unit
def test_sync_schedules_noop_without_scheduler():
    scheduler._scheduler = None
    scheduler.sync_schedules()


@pytest.mark.unit
def test_azure_token_and_error_detail():
    creds = AzureCredentials("t", "c", "s", "sub")
    ok = MagicMock()
    ok.status_code = 200
    ok.json.return_value = {"access_token": "tok"}
    with patch("app.providers.azure_infra.httpx.post", return_value=ok):
        assert azure_infra._get_token(creds) == "tok"
    fail = MagicMock()
    fail.status_code = 401
    fail.json.return_value = {"error_description": "bad client\nmore"}
    fail.text = "nope"
    with patch("app.providers.azure_infra.httpx.post", return_value=fail):
        with pytest.raises(azure_infra.AzureApiError, match="authentication failed"):
            azure_infra._get_token(creds)
    with patch("app.providers.azure_infra.httpx.post", side_effect=azure_infra.httpx.ConnectError("down")):
        with pytest.raises(azure_infra.AzureApiError, match="Could not reach"):
            azure_infra._get_token(creds)
    resp = MagicMock()
    resp.json.return_value = {"error": {"message": "denied"}}
    assert "denied" in azure_infra._error_detail(resp)


@pytest.mark.unit
def test_azure_run_query_success_and_failure():
    ok = MagicMock()
    ok.status_code = 200
    ok.json.return_value = {"data": [{"name": "rg1"}]}
    with patch("app.providers.azure_infra.httpx.post", return_value=ok):
        rows = azure_infra._run_query("tok", ["sub"], "Resources")
    assert rows[0]["name"] == "rg1"
    bad = MagicMock()
    bad.status_code = 500
    bad.json.return_value = {"error": "boom"}
    bad.text = "boom"
    with patch("app.providers.azure_infra.httpx.post", return_value=bad):
        with pytest.raises(azure_infra.AzureApiError, match="Resource Graph"):
            azure_infra._run_query("tok", [], "Resources")
