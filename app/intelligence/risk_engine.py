"""Risk Engine: gate actions by action-class x blast-radius, not by tool.

The core design principle of the DevOps Intelligence Layer is to classify the
action, not the tool. Gating "Terraform" is wrong; gating "an irreversible,
high-blast change to production" is right. This module encodes that matrix as a
pure function so both the workflow engine and the dashboard resolve gates the
same way.

The subtle rule the matrix must honour: safety-direction actions (rollback,
circuit-break, isolate) are never gated. You gate entry into risk, never the
escape from it.
"""
from dataclasses import dataclass
from typing import Literal

from app.skills.classification import ActionClass, BlastRadius

Environment = Literal["dev", "staging", "prod"]

Gate = Literal[
    "autonomous",
    "autonomous_logged",
    "auto_instant_undo",
    "auto_apply",
    "human_approval",
    "two_person",
]

_GATE_LABELS: dict[Gate, str] = {
    "autonomous": "Autonomous",
    "autonomous_logged": "Autonomous (logged)",
    "auto_instant_undo": "Auto + instant undo",
    "auto_apply": "Auto-apply",
    "human_approval": "Human approval",
    "two_person": "Two-person rule",
}
# Public alias so other modules can render gate labels consistently.
GATE_LABELS = _GATE_LABELS

# Ordering used to escalate a gate when blast radius is high.
# Public alias for break-glass one-step downgrade.
GATE_ORDER: tuple[Gate, ...] = (
    "autonomous",
    "autonomous_logged",
    "auto_instant_undo",
    "auto_apply",
    "human_approval",
    "two_person",
)
_GATE_ORDER = GATE_ORDER


@dataclass(frozen=True)
class GateDecision:
    """The resolved gate for one action plus a human-readable rationale."""

    gate: Gate
    label: str
    requires_approval: bool
    two_person: bool
    never_gated: bool
    rationale: str


def _is_prod(environment: Environment) -> bool:
    return environment == "prod"


def _base_gate(action_class: ActionClass, environment: Environment) -> Gate:
    """The action-class x environment matrix from the design."""
    prod = _is_prod(environment)
    if action_class == "read_diagnose":
        return "autonomous"
    if action_class == "safety_direction":
        return "autonomous"
    if action_class == "reversible_change":
        return "auto_instant_undo" if prod else "autonomous_logged"
    if action_class == "config_code_change":
        return "human_approval" if prod else "auto_apply"
    if action_class == "irreversible_high_blast":
        return "two_person" if prod else "human_approval"
    return "human_approval"


def _escalate(gate: Gate) -> Gate:
    idx = _GATE_ORDER.index(gate)
    return _GATE_ORDER[min(idx + 1, len(_GATE_ORDER) - 1)]


def classify(
    action_class: ActionClass,
    blast_radius: BlastRadius = "medium",
    environment: Environment = "prod",
) -> GateDecision:
    """Resolve the gate for an action.

    Safety-direction actions are never gated regardless of blast radius or
    environment. A high blast radius escalates a change-producing gate by one
    step (e.g. auto-apply becomes human approval) so a large change is never
    softer-gated than a small one.
    """
    if action_class == "safety_direction":
        return GateDecision(
            gate="autonomous",
            label=_GATE_LABELS["autonomous"],
            requires_approval=False,
            two_person=False,
            never_gated=True,
            rationale=(
                "Safety-direction action (rollback / mitigation) — never gate "
                "the exit from risk."
            ),
        )

    gate = _base_gate(action_class, environment)

    escalated = False
    if blast_radius == "high" and action_class in (
        "reversible_change",
        "config_code_change",
        "irreversible_high_blast",
    ):
        bumped = _escalate(gate)
        if bumped != gate:
            gate = bumped
            escalated = True

    rationale = (
        f"{action_class.replace('_', ' ')} in {environment} with "
        f"{blast_radius} blast radius"
    )
    if escalated:
        rationale += " (escalated one step for high blast radius)"

    return GateDecision(
        gate=gate,
        label=_GATE_LABELS[gate],
        requires_approval=gate in ("human_approval", "two_person"),
        two_person=gate == "two_person",
        never_gated=gate == "autonomous",
        rationale=rationale,
    )


def blast_radius_from_severity(
    base: BlastRadius, severity: str
) -> BlastRadius:
    """Escalate a skill's baseline blast radius when a finding is severe."""
    normalized = (severity or "").strip().lower()
    if normalized in ("critical", "high"):
        return "high"
    if normalized == "medium" and base == "low":
        return "medium"
    return base
