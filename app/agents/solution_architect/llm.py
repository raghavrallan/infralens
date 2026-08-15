"""AzureChatOpenAI client for the architect graph.

A second Azure OpenAI integration point: the raw client in ``app.azure_client``
cannot ``bind_tools()``. Settings-page credentials still drive this client via
``get_azure_config()``. Langfuse tracing uses ``langfuse.langchain.CallbackHandler``
rather than the ``langfuse.openai`` drop-in used by one-shot skills.
"""
from __future__ import annotations

from typing import Any, Optional

from app.core import observability
from app.core.config import get_azure_config

_llm: Any = None
_llm_signature: Optional[tuple[str, str, str, str, bool]] = None


def get_architect_llm() -> Any:
    """Return a LangChain Azure chat model, rebuilding when Settings change."""
    global _llm, _llm_signature
    from langchain_openai import AzureChatOpenAI

    config = get_azure_config()
    if not config.configured:
        raise RuntimeError("Azure OpenAI is not configured.")
    traced = observability.tracing_enabled()
    signature = (config.endpoint, config.api_key, config.deployment, config.api_version, traced)
    if _llm is None or _llm_signature != signature:
        _llm = AzureChatOpenAI(
            azure_endpoint=config.endpoint,
            api_key=config.api_key,
            azure_deployment=config.deployment,
            api_version=config.api_version,
            temperature=0.2,
        )
        _llm_signature = signature
    return _llm


def langchain_callbacks() -> list[Any]:
    if not observability.tracing_enabled():
        return []
    try:
        from langfuse.langchain import CallbackHandler

        return [CallbackHandler()]
    except Exception:
        return []


def invoke_config() -> dict[str, Any]:
    return {
        "callbacks": langchain_callbacks(),
        "metadata": observability.current_trace_metadata(),
        "run_name": observability.current_generation_name("solution-architect"),
    }
