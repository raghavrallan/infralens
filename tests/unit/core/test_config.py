"""Azure OpenAI config cache and server options."""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from app.core import config


@pytest.mark.unit
def test_azure_config_configured_requires_endpoint_and_key():
    assert config.AzureConfig().configured is False
    assert config.AzureConfig(endpoint="https://x", api_key="").configured is False
    assert config.AzureConfig(endpoint="", api_key="k").configured is False
    assert config.AzureConfig(endpoint="https://x", api_key="k").configured is True


@pytest.mark.unit
def test_get_server_options_defaults_and_override(monkeypatch):
    monkeypatch.delenv("APP_HOST", raising=False)
    monkeypatch.delenv("APP_PORT", raising=False)
    opts = config.get_server_options()
    assert opts["host"] == "127.0.0.1"
    assert opts["port"] == "8000"
    monkeypatch.setenv("APP_HOST", "0.0.0.0")
    monkeypatch.setenv("APP_PORT", "9000")
    opts = config.get_server_options()
    assert opts == {"host": "0.0.0.0", "port": "9000"}


@pytest.mark.unit
def test_get_config_value_returns_default_when_missing():
    session = MagicMock()
    session.get.return_value = None
    context = MagicMock()
    context.__enter__.return_value = session
    context.__exit__.return_value = False
    with patch("app.core.config.SessionLocal", return_value=context):
        assert config.get_config_value("missing", "fallback") == "fallback"


@pytest.mark.unit
def test_get_config_value_returns_stored_value():
    session = MagicMock()
    session.get.return_value = SimpleNamespace(value="stored")
    context = MagicMock()
    context.__enter__.return_value = session
    context.__exit__.return_value = False
    with patch("app.core.config.SessionLocal", return_value=context):
        assert config.get_config_value("k") == "stored"


@pytest.mark.unit
def test_set_config_values_inserts_and_updates():
    existing = SimpleNamespace(value="old")
    session = MagicMock()
    session.get.side_effect = [None, existing]
    context = MagicMock()
    context.__enter__.return_value = session
    context.__exit__.return_value = False
    with patch("app.core.config.SessionLocal", return_value=context):
        config.set_config_values({"new": "a", "old": "b"})
    session.add.assert_called()
    assert existing.value == "b"
    session.commit.assert_called()


@pytest.mark.unit
def test_get_azure_config_uses_defaults_and_cache():
    config.invalidate_azure_config_cache()
    session = MagicMock()
    session.execute.return_value.scalars.return_value = [
        SimpleNamespace(key="azure_openai_endpoint", value="https://example"),
        SimpleNamespace(key="azure_openai_api_key", value="secret"),
    ]
    context = MagicMock()
    context.__enter__.return_value = session
    context.__exit__.return_value = False
    with patch("app.core.config.SessionLocal", return_value=context):
        first = config.get_azure_config()
        second = config.get_azure_config()
    assert first.endpoint == "https://example"
    assert first.api_key == "secret"
    assert first.deployment == "gpt-4o"
    assert first.configured is True
    assert second.endpoint == first.endpoint
    config.invalidate_azure_config_cache()


@pytest.mark.unit
def test_set_azure_config_leaves_empty_key():
    with patch("app.core.config.set_config_values") as setter:
        with patch(
            "app.core.config.get_azure_config",
            return_value=config.AzureConfig(endpoint="e", api_key="kept"),
        ):
            result = config.set_azure_config("e", "", "gpt-4o", "2024-10-21")
    payload = setter.call_args.args[0]
    assert "azure_openai_api_key" not in payload
    assert result.api_key == "kept"
