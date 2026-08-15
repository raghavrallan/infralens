"""Stateful delivery tasks."""
from __future__ import annotations

import uuid
from typing import Any, Optional

from sqlalchemy import select

from app.core.db import DeliveryTask, ProjectArtifact, SessionLocal, _now
from app.platform.engineering import activity, artifacts as artifact_store
from app.platform.engineering.state_machine import (
    assert_transition,
    completion_blockers,
    missing_artifacts,
)

STAGE_LABELS = {
    "requirements": "Requirements",
    "architecture": "Architecture",
    "infrastructure": "Infrastructure",
    "security": "Security",
    "testing": "Testing",
    "cicd": "CI/CD",
    "deployment": "Deployment",
    "documentation": "Documentation",
    "validation": "Validation",
}


def _dict(row: DeliveryTask, *, attached: Optional[list[dict[str, Any]]] = None) -> dict[str, Any]:
    attached = attached or []
    names = [item.get("name") or item.get("filename") or "" for item in attached]
    missing = missing_artifacts(row.required_artifacts or [], names)
    validation_ok = bool(attached) and all(
        item.get("validation_status") in {"passed", "skipped"} or not (row.validation_rules or [])
        for item in attached
    ) if attached else not (row.validation_rules or [])
    if not row.validation_rules:
        validation_ok = True
    elif attached:
        validation_ok = all(item.get("validation_status") == "passed" for item in attached)
    else:
        validation_ok = False
    return {
        "id": row.id,
        "project_id": row.project_id,
        "delivery_run_id": row.delivery_run_id,
        "title": row.title,
        "description": row.description,
        "stage": row.stage,
        "stage_label": STAGE_LABELS.get(row.stage, row.stage.replace("_", " ").title()),
        "status": row.status,
        "priority": row.priority,
        "owner": row.owner,
        "depends_on": list(row.depends_on or []),
        "required_artifacts": list(row.required_artifacts or []),
        "validation_rules": list(row.validation_rules or []),
        "acceptance_criteria": list(row.acceptance_criteria or []),
        "evidence": list(row.evidence or []),
        "comments": list(row.comments or []),
        "ai_recommendation": row.ai_recommendation,
        "architecture_decision_id": row.architecture_decision_id,
        "requirement_id": row.requirement_id,
        "blocked_reason": row.blocked_reason,
        "artifacts": attached,
        "missing_artifacts": missing,
        "validation_ok": validation_ok,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
        "completed_at": row.completed_at.isoformat() if row.completed_at else None,
    }


def list_tasks(project_id: str, delivery_run_id: str = "") -> list[dict[str, Any]]:
    with SessionLocal() as session:
        stmt = select(DeliveryTask).where(DeliveryTask.project_id == project_id)
        if delivery_run_id:
            stmt = stmt.where(DeliveryTask.delivery_run_id == delivery_run_id)
        rows = session.scalars(stmt.order_by(DeliveryTask.created_at.asc())).all()
        artifact_rows = session.scalars(
            select(ProjectArtifact).where(ProjectArtifact.project_id == project_id)
        ).all()
    by_task: dict[str, list[dict[str, Any]]] = {}
    for item in artifact_rows:
        by_task.setdefault(item.task_id, []).append(artifact_store._dict(item))
    completed = {row.id for row in rows if row.status == "completed"}
    result = []
    for row in rows:
        payload = _dict(row, attached=by_task.get(row.id, []))
        unfinished = [dep for dep in (row.depends_on or []) if dep not in completed]
        if unfinished and row.status not in {"completed", "blocked"}:
            payload["blocked_reason"] = payload["blocked_reason"] or "Waiting on dependencies"
        result.append(payload)
    return result


def get_task(task_id: str) -> Optional[dict[str, Any]]:
    with SessionLocal() as session:
        row = session.get(DeliveryTask, task_id)
        if row is None:
            return None
        attached = artifact_store.list_artifacts(row.project_id, task_id=task_id)
        return _dict(row, attached=attached)


def create_task(
    *,
    project_id: str,
    title: str,
    description: str = "",
    stage: str = "infrastructure",
    delivery_run_id: str = "",
    priority: str = "medium",
    depends_on: Optional[list[str]] = None,
    required_artifacts: Optional[list] = None,
    validation_rules: Optional[list] = None,
    acceptance_criteria: Optional[list] = None,
    architecture_decision_id: str = "",
    requirement_id: str = "",
    ai_recommendation: str = "",
    status: str = "ready",
) -> dict[str, Any]:
    with SessionLocal() as session:
        row = DeliveryTask(
            id=str(uuid.uuid4()),
            project_id=project_id,
            delivery_run_id=delivery_run_id or "",
            title=title[:400],
            description=description or "",
            stage=stage[:32],
            status=status if depends_on else "ready",
            priority=priority,
            depends_on=depends_on or [],
            required_artifacts=required_artifacts or [],
            validation_rules=validation_rules or [],
            acceptance_criteria=acceptance_criteria or [],
            architecture_decision_id=architecture_decision_id or "",
            requirement_id=requirement_id or "",
            ai_recommendation=ai_recommendation or "",
            blocked_reason="Waiting on dependencies" if depends_on else "",
        )
        if depends_on:
            row.status = "blocked"
        session.add(row)
        session.commit()
        session.refresh(row)
        return _dict(row, attached=[])


def transition(task_id: str, target: str, *, actor: str = "", comment: str = "") -> dict[str, Any]:
    with SessionLocal() as session:
        row = session.get(DeliveryTask, task_id)
        if row is None:
            raise LookupError("Task not found")
        assert_transition(row.status, target)
        siblings = session.scalars(
            select(DeliveryTask).where(DeliveryTask.project_id == row.project_id)
        ).all()
        completed_ids = {item.id for item in siblings if item.status == "completed"}
        attached = artifact_store.list_artifacts(row.project_id, task_id=task_id)
        names = [item.get("name") or "" for item in attached]
        validation_ok = (
            not (row.validation_rules or [])
            or (attached and all(item.get("validation_status") == "passed" for item in attached))
        )
        if target == "completed":
            blockers = completion_blockers(
                status="approved" if row.status == "approved" else row.status,
                required_artifacts=list(row.required_artifacts or []),
                attached_names=names,
                validation_ok=validation_ok,
                dependency_ids=list(row.depends_on or []),
                completed_ids=completed_ids,
                acceptance=list(row.acceptance_criteria or []),
                evidence=list(row.evidence or attached),
            )
            if row.status != "approved":
                blockers = [item for item in blockers if "approved" in item] + [
                    b for b in blockers if "approved" not in b
                ]
            if blockers:
                raise ValueError("; ".join(blockers))
            row.completed_at = _now()
        if target == "blocked":
            unfinished = [dep for dep in (row.depends_on or []) if dep not in completed_ids]
            row.blocked_reason = comment or (
                f"Blocked by {len(unfinished)} dependencies" if unfinished else "Blocked"
            )
        else:
            row.blocked_reason = ""
        if comment:
            notes = list(row.comments or [])
            notes.append({"actor": actor, "text": comment, "at": _now().isoformat()})
            row.comments = notes
        row.status = target
        row.updated_at = _now()
        session.commit()
        session.refresh(row)
        payload = _dict(row, attached=attached)
    activity.record(
        payload["project_id"],
        f"task_{target}",
        actor=actor or "user",
        detail=payload["title"],
        ref_type="task",
        ref_id=task_id,
    )
    _refresh_dependents(payload["project_id"])
    return get_task(task_id) or payload


def add_evidence(task_id: str, *, name: str, note: str = "", actor: str = "") -> dict[str, Any]:
    with SessionLocal() as session:
        row = session.get(DeliveryTask, task_id)
        if row is None:
            raise LookupError("Task not found")
        evidence = list(row.evidence or [])
        evidence.append({"name": name, "note": note, "actor": actor, "at": _now().isoformat()})
        row.evidence = evidence
        row.updated_at = _now()
        session.commit()
    return get_task(task_id) or {}


def _refresh_dependents(project_id: str) -> None:
    tasks = list_tasks(project_id)
    completed = {item["id"] for item in tasks if item["status"] == "completed"}
    with SessionLocal() as session:
        for item in tasks:
            row = session.get(DeliveryTask, item["id"])
            if row is None:
                continue
            deps = list(row.depends_on or [])
            if not deps:
                continue
            unfinished = [dep for dep in deps if dep not in completed]
            if unfinished and row.status not in {"completed"}:
                row.status = "blocked"
                row.blocked_reason = "Waiting on dependencies"
            elif not unfinished and row.status == "blocked":
                row.status = "ready"
                row.blocked_reason = ""
            row.updated_at = _now()
        session.commit()
