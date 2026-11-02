"""LangChain tool wrappers over Solution Architect read-only adapters."""
from __future__ import annotations

from typing import Any, Optional

from app.agents.solution_architect import tools as architect_tools


def _tool_decorator():
    try:
        from langchain_core.tools import tool

        return tool
    except Exception:  # pragma: no cover
        def identity(**_kwargs: Any) -> Any:
            def wrap(fn: Any) -> Any:
                return fn

            return wrap

        return identity


tool = _tool_decorator()


@tool("get_cloud_inventory")
def get_cloud_inventory_tool(project_id: str) -> str:
    """Fetch connected cloud/GitHub inventory summary for a project."""
    return architect_tools.get_cloud_inventory(project_id)


@tool("search_precedent")
def search_precedent_tool(project_id: str) -> str:
    """Search engineering memory precedent for a project."""
    return architect_tools.search_precedent(project_id)


@tool("get_code_artifacts")
def get_code_artifacts_tool(project_id: str) -> str:
    """Read mapped repository / IaC artifacts for a project."""
    return architect_tools.get_code_artifacts(project_id)


@tool("preview_gate")
def preview_gate_tool(risk_class: str, blast_radius: str) -> str:
    """Preview Risk Engine gate for an action class and blast radius."""
    import json

    preview = architect_tools.preview_gate(risk_class, blast_radius)
    return json.dumps(preview, default=str)


def architect_langchain_tools() -> list[Any]:
    return [
        get_cloud_inventory_tool,
        search_precedent_tool,
        get_code_artifacts_tool,
        preview_gate_tool,
    ]


def bind_architect_tools(llm: Any) -> Any:
    """Optional bind_tools helper for future ReAct-style architect nodes."""
    tools = architect_langchain_tools()
    if hasattr(llm, "bind_tools"):
        return llm.bind_tools(tools)
    return llm
