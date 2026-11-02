"""Bounded ReAct-style debug loop for failed execution actions (feature-flagged).

When ``DEBUG_REACT_ENABLED`` is false, callers should keep using
``app.execution.debug_loop``. This module adds an explicit step budget and
escalation path without bypassing Risk Engine / create_action gates.
"""
from __future__ import annotations

from typing import Any, Literal, TypedDict

from app.agents.runtime.flags import feature_enabled
from app.agents.runtime.policies import default_debug_policy
from app.execution import debug_loop as legacy


class DebugState(TypedDict, total=False):
    action_id: str
    project_context: str
    step: int
    retries: int
    proposal: dict[str, Any]
    retry_action: dict[str, Any]
    status: Literal["proposed", "retry_created", "unsafe", "exhausted", "error"]
    notes: str


def react_enabled() -> bool:
    return feature_enabled("debug_react")


def run_debug_react(
    action_id: str,
    *,
    project_context: str = "",
    access_level: str = "ask_approval",
    requested_by: str = "debug_react",
    create_retry: bool = True,
) -> DebugState:
    """Observe → propose → (optional) create gated retry within policy budgets."""
    policy = default_debug_policy()
    state: DebugState = {
        "action_id": action_id,
        "project_context": project_context,
        "step": 0,
        "retries": 0,
        "status": "proposed",
        "notes": "",
    }
    if not policy.can_take_step(state["step"]):
        state["status"] = "exhausted"
        state["notes"] = "Step budget exhausted before propose."
        return state

    state["step"] += 1
    try:
        proposal = legacy.propose_fix(action_id, project_context=project_context)
    except Exception as exc:  # noqa: BLE001
        state["status"] = "error"
        state["notes"] = str(exc)[:2000]
        return state

    state["proposal"] = proposal
    if not proposal.get("retry_safe"):
        state["status"] = "unsafe"
        state["notes"] = proposal.get("notes") or "Model marked fix as not retry-safe."
        return state

    if not create_retry:
        return state

    if not policy.can_retry(state["retries"]):
        state["status"] = "exhausted"
        state["notes"] = "Retry budget exhausted."
        return state

    if "execute" in policy.require_gate_before:
        # create_retry_action always goes through execution service gates.
        pass

    state["step"] += 1
    state["retries"] += 1
    try:
        retry = legacy.create_retry_action(
            action_id,
            proposal,
            access_level=access_level,
            requested_by=requested_by,
        )
        state["retry_action"] = retry
        state["status"] = "retry_created"
    except Exception as exc:  # noqa: BLE001
        state["status"] = "error"
        state["notes"] = str(exc)[:2000]
    return state


def propose_or_react(
    action_id: str,
    *,
    project_context: str = "",
    access_level: str = "ask_approval",
    requested_by: str = "debug_loop",
    create_retry: bool = False,
) -> dict[str, Any]:
    """Facade: use ReAct path when flagged, else legacy propose_fix."""
    if react_enabled() and create_retry:
        return dict(
            run_debug_react(
                action_id,
                project_context=project_context,
                access_level=access_level,
                requested_by=requested_by,
                create_retry=True,
            )
        )
    if react_enabled():
        result = run_debug_react(
            action_id,
            project_context=project_context,
            create_retry=False,
        )
        return result.get("proposal") or {"status": result.get("status"), "notes": result.get("notes")}
    return legacy.propose_fix(action_id, project_context=project_context)
