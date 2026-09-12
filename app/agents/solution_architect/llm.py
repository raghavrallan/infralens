"""AzureChatOpenAI client for the architect graph.

Delegates to the shared agent runtime LLM factory so Architect, debug, and
future chat graphs share one Azure + Langfuse configuration path.
"""
from __future__ import annotations

from app.agents.runtime.llm import (
    get_architect_llm,
    get_chat_llm,
    invoke_config as _runtime_invoke_config,
    langchain_callbacks,
)

__all__ = [
    "get_architect_llm",
    "get_chat_llm",
    "invoke_config",
    "langchain_callbacks",
]


def invoke_config() -> dict:
    return _runtime_invoke_config(run_name="solution-architect")
