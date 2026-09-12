"""LangGraph StateGraph for Solution Architect (feature-flagged).

Reuses the same node functions as the sequential pipeline in ``graph.py``.
When ``ARCHITECT_LANGGRAPH`` is off, callers keep using ``run_pipeline``.
"""
from __future__ import annotations

import logging
from contextvars import ContextVar
from typing import Any, Callable, Literal, Optional

from app.agents.runtime.flags import feature_enabled
from app.agents.runtime.policies import default_architect_policy
from app.agents.solution_architect import governance
from app.agents.solution_architect.state import ArchitectState, empty_state

logger = logging.getLogger(__name__)

Emit = Callable[[dict[str, Any]], None]
_emit_var: ContextVar[Emit] = ContextVar("architect_emit", default=lambda _e: None)
_compiled: Any = None


def _emit(event: dict[str, Any]) -> None:
    _emit_var.get()(event)


def _wrap(node_fn: Callable[[ArchitectState, Emit], ArchitectState]) -> Callable[[ArchitectState], ArchitectState]:
    def _node(state: ArchitectState) -> ArchitectState:
        return node_fn(state, _emit)

    return _node


def _route_after_clarify(state: ArchitectState) -> Literal["pause", "explore"]:
    if state.get("awaiting_input"):
        return "pause"
    return "explore"


def _route_after_critique(state: ArchitectState) -> Literal["revise", "verify"]:
    if state.get("needs_revision"):
        return "revise"
    return "verify"


def _pause_node(state: ArchitectState) -> ArchitectState:
    """Persist awaiting_input checkpoint (same as sequential pipeline)."""
    governance.upsert_run(
        thread_id=state.get("thread_id") or "",
        project_id=state.get("project_id") or "",
        user_id=state.get("user") or "",
        objective=state.get("objective") or "",
        source=state.get("source") or "chat",
        tier=state.get("tier") or "T1",
        mode=state.get("mode") or "greenfield",
        status="awaiting_input",
        pending_question=state.get("pending_question") or "",
        checkpoint=dict(state),
    )
    return state


def _get_checkpointer() -> Any:
    try:
        from langgraph.checkpoint.postgres import PostgresSaver
        from psycopg_pool import ConnectionPool

        from app.core.db import get_database_url

        url = get_database_url().replace("postgresql+psycopg2://", "postgresql://").replace(
            "postgresql+psycopg://", "postgresql://"
        )
        pool = ConnectionPool(
            conninfo=url,
            kwargs={"autocommit": True, "prepare_threshold": 0},
            max_size=4,
            open=False,
        )
        pool.open()
        saver = PostgresSaver(pool)
        saver.setup()
        return saver
    except Exception as exc:  # noqa: BLE001
        logger.info("Architect LangGraph using MemorySaver (%s)", exc)
        from langgraph.checkpoint.memory import MemorySaver

        return MemorySaver()


def build_architect_graph(*, checkpointer: Any = None) -> Any:
    from langgraph.graph import END, StateGraph

    from app.agents.solution_architect import graph as nodes

    builder = StateGraph(ArchitectState)
    builder.add_node("clarify", _wrap(nodes.clarify))
    builder.add_node("pause", _pause_node)
    builder.add_node("explore", _wrap(nodes.explore))
    builder.add_node("design", _wrap(nodes.design))
    builder.add_node("critique", _wrap(nodes.critique))
    builder.add_node("verify", _wrap(nodes.verify))
    builder.add_node("finalize", _wrap(nodes.finalize))

    builder.set_entry_point("clarify")
    builder.add_conditional_edges(
        "clarify",
        _route_after_clarify,
        {"pause": "pause", "explore": "explore"},
    )
    builder.add_edge("pause", END)
    builder.add_edge("explore", "design")
    builder.add_edge("design", "critique")
    builder.add_conditional_edges(
        "critique",
        _route_after_critique,
        {"revise": "design", "verify": "verify"},
    )
    builder.add_edge("verify", "finalize")
    builder.add_edge("finalize", END)
    return builder.compile(checkpointer=checkpointer)


def get_compiled_graph() -> Any:
    global _compiled
    if _compiled is None:
        _compiled = build_architect_graph(checkpointer=_get_checkpointer())
    return _compiled


def reset_compiled_graph() -> None:
    global _compiled
    _compiled = None


def run_langgraph_pipeline(
    state: ArchitectState,
    emit: Optional[Emit] = None,
) -> ArchitectState:
    """Invoke the LangGraph architect. Resume uses governance pause, then entry at explore."""
    from app.agents.solution_architect import graph as nodes

    sink: Emit = emit or (lambda _event: None)
    token = _emit_var.set(sink)
    try:
        paused = governance.load_paused(state.get("thread_id") or "")
        if paused and not state.get("plan_only"):
            answer = state.get("objective") or ""
            state = empty_state(**{k: v for k, v in paused.items() if k != "_run_id"})
            qa = list(state.get("clarifying_qa") or [])
            qa.append({"q": str(paused.get("pending_question") or ""), "a": answer})
            state["clarifying_qa"] = qa
            state["awaiting_input"] = False
            state["pending_question"] = ""
            state["needs_revision"] = False
            # Resume path: skip clarify; run explore→… via sequential node calls
            # inside a mini-graph starting at explore for checkpoint continuity.
            state = nodes.explore(state, sink)
            while True:
                state = nodes.design(state, sink)
                state = nodes.critique(state, sink)
                if state.get("needs_revision"):
                    continue
                break
            state = nodes.verify(state, sink)
            return nodes.finalize(state, sink)

        graph = get_compiled_graph()
        thread_id = state.get("thread_id") or "architect"
        config = {
            "configurable": {"thread_id": f"architect:{thread_id}"},
            "recursion_limit": default_architect_policy().max_steps,
        }
        try:
            from app.agents.runtime.llm import invoke_config

            config.update(invoke_config(run_name="solution-architect-langgraph"))
        except Exception:
            pass
        result = graph.invoke(dict(state), config=config)
        return result  # type: ignore[return-value]
    finally:
        _emit_var.reset(token)


def langgraph_enabled() -> bool:
    return feature_enabled("architect_langgraph")
