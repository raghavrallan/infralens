"""Thin wrapper around the Azure OpenAI chat completions API.

Reads Azure OpenAI settings from the Postgres-backed config so credentials can
be updated at runtime from the Settings page. The underlying client is rebuilt
whenever the stored endpoint / key / API version changes.

There are two Azure OpenAI consumers:
  1. This module — used by one-shot skills and the orchestrator. When Langfuse
     credentials are configured, the ``langfuse.openai`` drop-in AzureOpenAI
     client traces completions (model, tokens, latency) with session_id /
     user_id from the current observability context.
  2. ``app.agents.solution_architect.llm`` — LangChain ``AzureChatOpenAI`` so
     the architect graph can ``bind_tools()``. Tracing there uses
     ``langfuse.langchain.CallbackHandler`` plus the same metadata helper.

The raw client here cannot bind tools; do not merge the two without losing
agentic tool calling.
"""
from typing import Any, Iterator, Optional

from app import observability
from app.config import AzureConfig, get_azure_config

_client: Any = None
_client_signature: Optional[tuple[str, str, str, bool]] = None


class AzureOpenAINotConfiguredError(RuntimeError):
    """Raised when a live call is attempted without Azure credentials."""


def _azure_openai_cls():
    """Prefer Langfuse-wrapped AzureOpenAI when tracing is enabled."""
    observability.ensure_host_alias()
    if observability.tracing_enabled():
        from langfuse.openai import AzureOpenAI as LangfuseAzureOpenAI

        return LangfuseAzureOpenAI
    from openai import AzureOpenAI

    return AzureOpenAI


def _get_client(config: AzureConfig) -> Any:
    """Return a client for the current config, rebuilding it if settings change."""
    global _client, _client_signature
    if not config.configured:
        raise AzureOpenAINotConfiguredError(
            "Azure OpenAI is not configured. Open Settings and add your Azure "
            "OpenAI endpoint and API key."
        )
    traced = observability.tracing_enabled()
    signature = (config.endpoint, config.api_key, config.api_version, traced)
    if _client is None or _client_signature != signature:
        cls = _azure_openai_cls()
        _client = cls(
            azure_endpoint=config.endpoint,
            api_key=config.api_key,
            api_version=config.api_version,
        )
        _client_signature = signature
    return _client


def _call_kwargs(
    config: AzureConfig,
    messages: list[dict[str, Any]],
    temperature: float,
    *,
    tools: Optional[list[dict[str, Any]]] = None,
    tool_choice: Optional[Any] = None,
    response_format: Optional[dict[str, Any]] = None,
    stream: bool = False,
    name: Optional[str] = None,
) -> dict[str, Any]:
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
    if stream:
        kwargs["stream"] = True
    if observability.tracing_enabled():
        kwargs["name"] = name or observability.current_generation_name()
        metadata = observability.current_trace_metadata()
        if metadata:
            kwargs["metadata"] = metadata
        prompt = observability.take_active_prompt()
        if prompt is not None:
            kwargs["langfuse_prompt"] = prompt
    return kwargs


def chat(
    messages: list[dict[str, Any]],
    tools: Optional[list[dict[str, Any]]] = None,
    tool_choice: Optional[Any] = None,
    temperature: float = 0.2,
    response_format: Optional[dict[str, Any]] = None,
    name: Optional[str] = None,
) -> Any:
    """Call the configured chat deployment and return the raw completion."""
    config = get_azure_config()
    client = _get_client(config)
    kwargs = _call_kwargs(
        config,
        messages,
        temperature,
        tools=tools,
        tool_choice=tool_choice,
        response_format=response_format,
        name=name,
    )
    return client.chat.completions.create(**kwargs)


def stream_chat(
    messages: list[dict[str, Any]],
    temperature: float = 0.2,
    name: Optional[str] = None,
) -> Iterator[str]:
    """Stream a chat completion, yielding text deltas as they arrive."""
    config = get_azure_config()
    client = _get_client(config)
    kwargs = _call_kwargs(
        config, messages, temperature, stream=True, name=name
    )
    stream = client.chat.completions.create(**kwargs)
    for chunk in stream:
        if not chunk.choices:
            continue
        delta = chunk.choices[0].delta
        piece = getattr(delta, "content", None)
        if piece:
            yield piece
