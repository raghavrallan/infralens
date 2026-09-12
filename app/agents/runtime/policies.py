"""Bounded loop budgets shared by Architect, debug ReAct, and future graphs."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal


OnExhausted = Literal["escalate", "stop_with_summary"]


@dataclass(frozen=True)
class AgentLoopPolicy:
    max_steps: int = 12
    max_revisions: int = 2
    max_tool_calls: int = 20
    max_retries: int = 3
    allowed_tools: tuple[str, ...] = ()
    require_gate_before: tuple[str, ...] = ("execute", "write", "apply")
    on_budget_exhausted: OnExhausted = "stop_with_summary"

    def remaining_revisions(self, used: int) -> int:
        return max(0, self.max_revisions - max(0, used))

    def can_revise(self, used: int) -> bool:
        return self.remaining_revisions(used) > 0

    def can_retry(self, used: int) -> bool:
        return used < self.max_retries

    def can_take_step(self, used: int) -> bool:
        return used < self.max_steps


def default_architect_policy() -> AgentLoopPolicy:
    return AgentLoopPolicy(
        max_steps=12,
        max_revisions=2,
        max_tool_calls=30,
        require_gate_before=("execute", "write", "apply"),
        on_budget_exhausted="stop_with_summary",
    )


def default_debug_policy() -> AgentLoopPolicy:
    return AgentLoopPolicy(
        max_steps=8,
        max_revisions=0,
        max_tool_calls=12,
        max_retries=3,
        require_gate_before=("execute", "write", "apply"),
        on_budget_exhausted="escalate",
    )


def default_chat_policy() -> AgentLoopPolicy:
    return AgentLoopPolicy(
        max_steps=10,
        max_revisions=0,
        max_tool_calls=15,
        on_budget_exhausted="stop_with_summary",
    )
