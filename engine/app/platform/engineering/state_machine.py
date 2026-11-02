"""Validated status transitions for delivery tasks."""
from __future__ import annotations

from typing import Iterable

STATUSES = (
    "not_started",
    "ready",
    "in_progress",
    "validation_required",
    "validation_failed",
    "blocked",
    "ready_for_review",
    "approved",
    "completed",
)

# Explicit edges. Anything else is rejected.
TRANSITIONS: dict[str, frozenset[str]] = {
    "not_started": frozenset({"ready", "blocked"}),
    "ready": frozenset({"in_progress", "blocked"}),
    "in_progress": frozenset(
        {"validation_required", "blocked", "ready_for_review"}
    ),
    "validation_required": frozenset(
        {"validation_failed", "ready_for_review", "blocked"}
    ),
    "validation_failed": frozenset({"in_progress", "blocked"}),
    "blocked": frozenset({"ready", "in_progress"}),
    "ready_for_review": frozenset({"approved", "in_progress", "blocked"}),
    "approved": frozenset({"completed"}),
    "completed": frozenset(),
}

TERMINAL = "completed"


def can_transition(current: str, target: str) -> bool:
    return target in TRANSITIONS.get(current or "not_started", frozenset())


def assert_transition(current: str, target: str) -> None:
    if current == target:
        return
    if not can_transition(current, target):
        raise ValueError(f"Cannot move task from '{current}' to '{target}'")


def missing_artifacts(
    required: Iterable[dict | str],
    attached_names: Iterable[str],
) -> list[str]:
    have = {str(name).lower() for name in attached_names}
    missing: list[str] = []
    for item in required or []:
        name = item.get("name") if isinstance(item, dict) else str(item)
        if name and name.lower() not in have and not any(
            str(name).lower() in existing for existing in have
        ):
            missing.append(str(name))
    return missing


def completion_blockers(
    *,
    status: str,
    required_artifacts: list,
    attached_names: list[str],
    validation_ok: bool,
    dependency_ids: list[str],
    completed_ids: set[str],
    acceptance: list,
    evidence: list,
) -> list[str]:
    """Return reasons the task cannot be marked completed."""
    blockers: list[str] = []
    if status != "approved" and status != "completed":
        blockers.append("Task must be approved before it can be completed")
    missing = missing_artifacts(required_artifacts, attached_names)
    if missing:
        blockers.append("Missing artifacts: " + ", ".join(missing))
    if not validation_ok:
        blockers.append("Validation has not passed")
    unfinished = [dep for dep in (dependency_ids or []) if dep and dep not in completed_ids]
    if unfinished:
        blockers.append(f"Blocked by {len(unfinished)} incomplete dependenc" + (
            "y" if len(unfinished) == 1 else "ies"
        ))
    if acceptance and not evidence:
        blockers.append("Acceptance criteria require evidence")
    return blockers
