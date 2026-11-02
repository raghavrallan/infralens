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
import re
from dataclasses import dataclass
from typing import Any, Literal

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

_ACTION_CLASSES: frozenset[str] = frozenset(
    {
        "read_diagnose",
        "reversible_change",
        "config_code_change",
        "irreversible_high_blast",
        "safety_direction",
    }
)
_BLAST_RADII: frozenset[str] = frozenset({"low", "medium", "high"})
_TOKEN_RE = re.compile(r"[a-z]+")


def normalize_blast_radius(value: Any, default: BlastRadius = "medium") -> BlastRadius:
    """Coerce LLM/free-text blast radius down to low|medium|high for varchar(16)."""
    raw = str(value or "").strip().lower()
    if raw in _BLAST_RADII:
        return raw  # type: ignore[return-value]
    tokens = set(_TOKEN_RE.findall(raw))
    if "high" in tokens:
        return "high"
    if "medium" in tokens:
        return "medium"
    if "low" in tokens:
        return "low"
    return default


def normalize_action_class(value: Any, default: ActionClass = "config_code_change") -> ActionClass:
    """Coerce LLM/free-text action class onto the Risk Engine taxonomy."""
    raw = str(value or "").strip().lower().replace(" ", "_").replace("-", "_")
    if raw in _ACTION_CLASSES:
        return raw  # type: ignore[return-value]
    if raw in _BLAST_RADII:
        return default
    if "irreversible" in raw or "destroy" in raw:
        return "irreversible_high_blast"
    if "safety" in raw or "rollback" in raw or "mitigat" in raw:
        return "safety_direction"
    if "read" in raw or "diagnose" in raw:
        return "read_diagnose"
    if "reversible" in raw:
        return "reversible_change"
    if "config" in raw or "code" in raw:
        return "config_code_change"
    return default


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
    blast_radius = normalize_blast_radius(blast_radius)
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
