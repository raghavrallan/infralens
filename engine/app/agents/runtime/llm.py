"""Shared LangChain Azure chat model + Langfuse callbacks.

Solution Architect historically owned this client in
``app.agents.solution_architect.llm``. All new graphs should import from here.
"""
from __future__ import annotations

from typing import Any, Optional

from app.core import observability
from app.core.config import get_azure_config

_llm: Any = None
_llm_signature: Optional[tuple[str, str, str, str, bool, float]] = None


def get_chat_llm(*, temperature: float = 0.2) -> Any:
    """Return a LangChain AzureChatOpenAI, rebuilding when Settings change."""
    global _llm, _llm_signature
    from langchain_openai import AzureChatOpenAI

    config = get_azure_config()
    if not config.configured:
        raise RuntimeError("Azure OpenAI is not configured.")
    traced = observability.tracing_enabled()
    signature = (
        config.endpoint,
        config.api_key,
        config.deployment,
        config.api_version,
        traced,
        temperature,
    )
    if _llm is None or _llm_signature != signature:
        _llm = AzureChatOpenAI(
            azure_endpoint=config.endpoint,
            api_key=config.api_key,
            azure_deployment=config.deployment,
            api_version=config.api_version,
            temperature=temperature,
        )
        _llm_signature = signature
    return _llm


# Backward-compatible alias used by architect modules.
get_architect_llm = get_chat_llm


def langchain_callbacks() -> list[Any]:
    if not observability.tracing_enabled():
        return []
    try:
        from langfuse.langchain import CallbackHandler

        return [CallbackHandler()]
    except Exception:
        return []


def invoke_config(*, run_name: str = "agent-runtime") -> dict[str, Any]:
    return {
        "callbacks": langchain_callbacks(),
        "metadata": observability.current_trace_metadata(),
        "run_name": observability.current_generation_name(run_name),
    }
