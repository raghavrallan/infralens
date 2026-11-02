"""Optional LangGraph for chat Auto multi-agent (Phase 5 — scaffold).

Disabled unless ``CHAT_LANGGRAPH=true``. Default chat path remains
``app.chat.orchestrator`` plan → skills → synthesise.
"""
from __future__ import annotations

from typing import Any

from app.agents.runtime.flags import feature_enabled


def chat_langgraph_enabled() -> bool:
    return feature_enabled("chat_langgraph")


def run_chat_graph_placeholder(_args: dict[str, Any]) -> dict[str, Any]:
    """Reserved for checkpointed multi-skill chat plans.

    Not wired into the orchestrator yet — enable only after Architect + n8n
    paths are stable.
    """
    raise NotImplementedError(
        "Chat LangGraph is scaffolded but not enabled. Keep using the orchestrator."
    )
