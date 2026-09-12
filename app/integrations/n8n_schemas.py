"""Outbound integration event payloads (n8n / generic webhooks)."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal, Optional
from uuid import uuid4

EventName = Literal[
    "approval.created",
    "approval.expiring",
    "approval.decided",
    "delivery.stage_changed",
    "architecture.ready_for_accept",
    "execution.failed",
    "workflow.run_completed",
]


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def envelope(
    event: EventName,
    *,
    project_id: str = "",
    data: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    return {
        "id": str(uuid4()),
        "event": event,
        "occurred_at": _now_iso(),
        "project_id": project_id or "",
        "source": "infralens",
        "data": data or {},
    }


def approval_created(
    *,
    approval_id: str,
    finding_id: str,
    project_id: str,
    gate: str,
    severity: str = "",
    title: str = "",
    expires_at: str = "",
    deep_link: str = "",
) -> dict[str, Any]:
    return envelope(
        "approval.created",
        project_id=project_id,
        data={
            "approval_id": approval_id,
            "finding_id": finding_id,
            "gate": gate,
            "severity": severity,
            "title": title,
            "expires_at": expires_at,
            "deep_link": deep_link or f"/dashboard/approvals/?highlight={approval_id}",
        },
    )


def approval_decided(
    *,
    approval_id: str,
    project_id: str,
    decision: str,
    decided_by: str = "",
    title: str = "",
) -> dict[str, Any]:
    return envelope(
        "approval.decided",
        project_id=project_id,
        data={
            "approval_id": approval_id,
            "decision": decision,
            "decided_by": decided_by,
            "title": title,
        },
    )


def delivery_stage_changed(
    *,
    delivery_run_id: str,
    project_id: str,
    from_stage: str,
    to_stage: str,
    actor: str = "",
) -> dict[str, Any]:
    return envelope(
        "delivery.stage_changed",
        project_id=project_id,
        data={
            "delivery_run_id": delivery_run_id,
            "from_stage": from_stage,
            "to_stage": to_stage,
            "actor": actor,
        },
    )


def architecture_ready(
    *,
    run_id: str,
    project_id: str,
    objective: str = "",
    tier: str = "",
    deep_link: str = "",
) -> dict[str, Any]:
    return envelope(
        "architecture.ready_for_accept",
        project_id=project_id,
        data={
            "architecture_run_id": run_id,
            "objective": objective,
            "tier": tier,
            "deep_link": deep_link or f"/dashboard/architecture/?highlight={run_id}",
        },
    )


def execution_failed(
    *,
    action_id: str,
    project_id: str = "",
    error: str = "",
    provider: str = "",
) -> dict[str, Any]:
    return envelope(
        "execution.failed",
        project_id=project_id,
        data={
            "action_id": action_id,
            "error": (error or "")[:2000],
            "provider": provider,
        },
    )


def workflow_run_completed(
    *,
    run_id: str,
    workflow_id: str,
    project_id: str,
    status: str,
    finding_count: int = 0,
) -> dict[str, Any]:
    return envelope(
        "workflow.run_completed",
        project_id=project_id,
        data={
            "run_id": run_id,
            "workflow_id": workflow_id,
            "status": status,
            "finding_count": finding_count,
        },
    )
