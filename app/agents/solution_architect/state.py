"""Typed architect graph state."""
from __future__ import annotations

from typing import Any, Literal, Optional, TypedDict

Tier = Literal["T1", "T2", "T3"]
Mode = Literal["greenfield", "brownfield"]
Source = Literal["chat", "delivery"]


class ArchitectState(TypedDict, total=False):
    objective: str
    project_id: str
    user: str
    constraints: str
    seed_context: str
    tier: Tier
    mode: Mode
    source: Source
    plan_only: bool
    thread_id: str
    clarifying_qa: list[dict[str, str]]
    exploration_notes: str
    candidates: list[dict[str, Any]]
    critique_notes: str
    verify_notes: str
    revision_count: int
    decisions: list[dict[str, Any]]
    assumptions: list[str]
    hld: str
    mermaid: str
    plan_steps: list[dict[str, str]]
    awaiting_input: bool
    pending_question: str
    reply: str
    messages: list[dict[str, Any]]


def empty_state(**overrides: Any) -> ArchitectState:
    state: ArchitectState = {
        "objective": "",
        "project_id": "",
        "user": "",
        "constraints": "",
        "seed_context": "",
        "tier": "T1",
        "mode": "greenfield",
        "source": "chat",
        "plan_only": False,
        "thread_id": "",
        "clarifying_qa": [],
        "exploration_notes": "",
        "candidates": [],
        "critique_notes": "",
        "verify_notes": "",
        "revision_count": 0,
        "decisions": [],
        "assumptions": [],
        "hld": "",
        "mermaid": "",
        "plan_steps": [],
        "awaiting_input": False,
        "pending_question": "",
        "reply": "",
        "messages": [],
    }
    state.update(overrides)  # type: ignore[typeddict-item]
    return state


def infer_tier(text: str) -> Tier:
    lowered = (text or "").lower()
    enterprise = (
        "pci", "multi-region", "multi region", "enterprise", "regulatory",
        "hipaa", "fedramp", "several teams", "multiple domains",
    )
    platform = (
        "event bus", "microserv", "split the monolith", "bounded context",
        "multi-service", "several services", "shared data",
    )
    if any(token in lowered for token in enterprise):
        return "T3"
    if any(token in lowered for token in platform):
        return "T2"
    return "T1"
