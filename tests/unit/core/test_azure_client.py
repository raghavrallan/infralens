"""Azure OpenAI client rebuild, kwargs, and not-configured errors."""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from app.core import azure_client
from app.core.config import AzureConfig


@pytest.mark.unit
def test_get_client_raises_when_unconfigured():
    azure_client._client = None
    azure_client._client_signature = None
    with pytest.raises(azure_client.AzureOpenAINotConfiguredError):
        azure_client._get_client(AzureConfig())


@pytest.mark.unit
def test_get_client_rebuilds_when_signature_changes():
    azure_client._client = None
    azure_client._client_signature = None
    fake_cls = MagicMock()
    instance = MagicMock()
    fake_cls.return_value = instance
    cfg = AzureConfig(endpoint="https://e", api_key="k", api_version="v1")
    with patch("app.core.azure_client._azure_openai_cls", return_value=fake_cls):
        first = azure_client._get_client(cfg)
        second = azure_client._get_client(cfg)
    assert first is second is instance
    fake_cls.assert_called_once()
    azure_client._client = None
    azure_client._client_signature = None


@pytest.mark.unit
def test_call_kwargs_include_tools_stream_and_tracing_metadata():
    cfg = AzureConfig(endpoint="https://e", api_key="k", deployment="gpt-4o")
    with patch("app.core.azure_client.observability.tracing_enabled", return_value=True):
        with patch(
            "app.core.azure_client.observability.current_trace_metadata",
            return_value={"langfuse_session_id": "s"},
        ):
            with patch(
                "app.core.azure_client.observability.take_active_prompt",
                return_value="prompt",
            ):
                kwargs = azure_client._call_kwargs(
                    cfg,
                    [{"role": "user", "content": "hi"}],
                    0.1,
                    tools=[{"type": "function"}],
                    tool_choice="auto",
                    response_format={"type": "json_object"},
                    stream=True,
                    name="gen",
                )
    assert kwargs["model"] == "gpt-4o"
    assert kwargs["tools"]
    assert kwargs["stream"] is True
    assert kwargs["metadata"]["langfuse_session_id"] == "s"
    assert kwargs["langfuse_prompt"] == "prompt"
    assert kwargs["name"] == "gen"


@pytest.mark.unit
def test_chat_and_stream_chat_delegate_to_client():
    cfg = AzureConfig(endpoint="https://e", api_key="k", deployment="dep")
    client = MagicMock()
    completion = SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content="ok"))])
    client.chat.completions.create.return_value = completion
    chunk = SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(content="hi"))])
    empty = SimpleNamespace(choices=[])
    client.chat.completions.create.side_effect = [completion, [empty, chunk]]
    with patch("app.core.azure_client.get_azure_config", return_value=cfg):
        with patch("app.core.azure_client._get_client", return_value=client):
            result = azure_client.chat([{"role": "user", "content": "q"}])
            pieces = list(azure_client.stream_chat([{"role": "user", "content": "q"}]))
    assert result is completion
    assert pieces == ["hi"]
