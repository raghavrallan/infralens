"""Connection secret masking and OAuth option/start guards."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from app.platform import connections, oauth_providers


@pytest.mark.unit
def test_mask_short_and_long_secrets():
    assert connections._mask("") == ""
    assert connections._mask("ab") == "**"
    assert connections._mask("abcd") == "****"
    assert connections._mask("supersecret") == "*******cret"


@pytest.mark.unit
def test_set_connection_rejects_unknown_provider():
    with pytest.raises(ValueError, match="Unknown provider"):
        connections.set_connection("p1", "gcp", "token", {})
    with pytest.raises(ValueError, match="Unknown provider"):
        connections.remove_connection("p1", "gcp")


@pytest.mark.unit
def test_status_disconnected_when_missing():
    session = MagicMock()
    session.get.return_value = None
    context = MagicMock()
    context.__enter__.return_value = session
    context.__exit__.return_value = False
    with patch("app.platform.connections.SessionLocal", return_value=context):
        status = connections.status("p1", "azure")
        secrets = connections.get_secret_fields("p1", "azure")
        all_status = connections.all_status("p1")
    assert status == {"provider": "azure", "connected": False}
    assert secrets is None
    assert [row["provider"] for row in all_status] == list(connections.PROVIDERS)


@pytest.mark.unit
def test_status_masks_secrets_and_exposes_identity():
    row = MagicMock()
    row.method = "client_secret"
    row.fields = {"client_id": "abc", "client_secret": "supersecretvalue"}
    row.connected_at = None
    session = MagicMock()
    session.get.return_value = row
    context = MagicMock()
    context.__enter__.return_value = session
    context.__exit__.return_value = False
    with patch("app.platform.connections.SessionLocal", return_value=context):
        status = connections.status("p1", "azure")
        raw = connections.get_secret_fields("p1", "azure")
    assert status["connected"] is True
    assert status["identity"] == "abc"
    assert "supersecretvalue" not in status["hint"]
    assert status["hint"].endswith("alue")
    assert raw["client_secret"] == "supersecretvalue"


@pytest.mark.unit
def test_oauth_options_without_env(monkeypatch):
    monkeypatch.delenv("GITHUB_OAUTH_CLIENT_ID", raising=False)
    monkeypatch.delenv("GITHUB_OAUTH_CLIENT_SECRET", raising=False)
    monkeypatch.delenv("AZURE_OAUTH_CLIENT_ID", raising=False)
    opts = oauth_providers.auth_options()
    assert opts["github"]["oauth"] is False
    assert opts["github"]["pat"] is True
    assert "oauth" in opts["github"]["methods"]
    assert opts["azure"]["secrets"] is True


@pytest.mark.unit
def test_github_oauth_start_requires_config(monkeypatch):
    monkeypatch.delenv("GITHUB_OAUTH_CLIENT_ID", raising=False)
    monkeypatch.delenv("GITHUB_OAUTH_CLIENT_SECRET", raising=False)
    with pytest.raises(RuntimeError, match="not configured"):
        oauth_providers.start_github_oauth(project_id="p1", request_base="http://localhost:8000")


@pytest.mark.unit
def test_finish_oauth_rejects_invalid_state():
    with pytest.raises(ValueError, match="Invalid or expired"):
        oauth_providers.finish_github_oauth(code="x", state="nope", request_base="http://x")
    with pytest.raises(ValueError, match="Invalid or expired"):
        oauth_providers.finish_azure_oauth(code="x", state="nope", request_base="http://x")
