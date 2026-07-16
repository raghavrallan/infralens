"""Thin wrapper around the Azure OpenAI chat completions API.

Reads Azure OpenAI settings from the Postgres-backed config so credentials can
be updated at runtime from the Settings page. The underlying client is rebuilt
whenever the stored endpoint / key / API version changes.
"""
from typing import Any, Iterator, Optional

from openai import AzureOpenAI

from app.config import AzureConfig, get_azure_config

_client: Optional[AzureOpenAI] = None
_client_signature: Optional[tuple[str, str, str]] = None


class AzureOpenAINotConfiguredError(RuntimeError):
    """Raised when a live call is attempted without Azure credentials."""


def _get_client(config: AzureConfig) -> AzureOpenAI:
    """Return a client for the current config, rebuilding it if settings change."""
    global _client, _client_signature
    if not config.configured:
        raise AzureOpenAINotConfiguredError(
            "Azure OpenAI is not configured. Open Settings and add your Azure "
            "OpenAI endpoint and API key."
        )
    signature = (config.endpoint, config.api_key, config.api_version)
    if _client is None or _client_signature != signature:
        _client = AzureOpenAI(
            azure_endpoint=config.endpoint,
            api_key=config.api_key,
            api_version=config.api_version,
        )
        _client_signature = signature
    return _client


def chat(
    messages: list[dict[str, Any]],
    tools: Optional[list[dict[str, Any]]] = None,
    tool_choice: Optional[Any] = None,
    temperature: float = 0.2,
    response_format: Optional[dict[str, Any]] = None,
) -> Any:
    """Call the configured chat deployment and return the raw completion."""
    config = get_azure_config()
    client = _get_client(config)

    kwargs: dict[str, Any] = {
        "model": config.deployment,
        "messages": messages,
        "temperature": temperature,
    }
    if tools:
        kwargs["tools"] = tools
    if tool_choice is not None:
        kwargs["tool_choice"] = tool_choice
    if response_format is not None:
        kwargs["response_format"] = response_format

    return client.chat.completions.create(**kwargs)


def stream_chat(
    messages: list[dict[str, Any]],
    temperature: float = 0.2,
) -> Iterator[str]:
    """Stream a chat completion, yielding text deltas as they arrive."""
    config = get_azure_config()
    client = _get_client(config)

    stream = client.chat.completions.create(
        model=config.deployment,
        messages=messages,
        temperature=temperature,
        stream=True,
    )
    for chunk in stream:
        if not chunk.choices:
            continue
        delta = chunk.choices[0].delta
        piece = getattr(delta, "content", None)
        if piece:
            yield piece
