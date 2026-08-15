"""Persist ADRs and gated findings from architect decisions into the existing inbox."""
from __future__ import annotations

import uuid
from typing import Any, Optional

from sqlalchemy import select

from app.core.db import (
    ArchitectureDecision,
    ArchitectureRun,
    EngineeringMemory,
    SessionLocal,
    Workflow,
    _now,
)
from app.intelligence import risk_engine
from app.intelligence import workflows as store

ARCHITECT_WORKFLOW_NAME = "Solution Architect Runs"
HIGH_GATES = frozenset({"two_person"})


def ensure_architect_workflow(project_id: str) -> str:
    with SessionLocal() as session:
        row = session.scalar(
            select(Workflow).where(
                Workflow.project_id == project_id,
                Workflow.name == ARCHITECT_WORKFLOW_NAME,
            )
        )
        if row is not None:
            return row.id
        workflow = Workflow(
            id=str(uuid.uuid4()),
            project_id=project_id,
            name=ARCHITECT_WORKFLOW_NAME,
            objective="FK home for Solution Architect findings — never scheduled.",
            module="iac",
            environment="prod",
            skills=[],
            schedule_cron="",
            enabled=False,
        )
        session.add(workflow)
        session.commit()
        return workflow.id


def upsert_run(
    *,
    thread_id: str,
    project_id: str,
    user_id: str,
    objective: str,
    source: str,
    tier: str,
    mode: str,
    status: str,
    pending_question: str = "",
    checkpoint: Optional[dict[str, Any]] = None,
) -> str:
    with SessionLocal() as session:
        row = session.scalar(
            select(ArchitectureRun)
            .where(ArchitectureRun.thread_id == thread_id)
            .order_by(ArchitectureRun.created_at.desc())
        )
        if row is None or row.status in {"succeeded", "failed"}:
            row = ArchitectureRun(
                id=str(uuid.uuid4()),
                thread_id=thread_id,
                project_id=project_id,
                user_id=user_id,
            )
            session.add(row)
        row.objective = (objective or "")[:8000]
        row.tier = tier or "T1"
        row.mode = mode or "greenfield"
        row.source = source or "chat"
        row.status = status
        row.pending_question = pending_question or ""
        if checkpoint is not None:
            row.checkpoint = checkpoint
        row.updated_at = _now()
        session.commit()
        return row.id


def load_paused(thread_id: str) -> Optional[dict[str, Any]]:
    with SessionLocal() as session:
        row = session.scalar(
            select(ArchitectureRun)
            .where(
                ArchitectureRun.thread_id == thread_id,
                ArchitectureRun.status == "awaiting_input",
            )
            .order_by(ArchitectureRun.created_at.desc())
        )
        if row is None:
            return None
        payload = dict(row.checkpoint or {})
        payload["_run_id"] = row.id
        payload["pending_question"] = row.pending_question
        return payload


def list_runs(project_id: str, limit: int = 20) -> list[dict[str, Any]]:
    with SessionLocal() as session:
        rows = session.scalars(
            select(ArchitectureRun)
            .where(ArchitectureRun.project_id == project_id)
            .order_by(ArchitectureRun.updated_at.desc())
            .limit(limit)
        )
        result: list[dict[str, Any]] = []
        for row in rows:
            decisions = session.scalars(
                select(ArchitectureDecision).where(ArchitectureDecision.run_id == row.id)
            )
            result.append(
                {
                    "id": row.id,
                    "thread_id": row.thread_id,
                    "project_id": row.project_id,
                    "objective": row.objective,
                    "tier": row.tier,
                    "mode": row.mode,
                    "source": row.source,
                    "status": row.status,
                    "created_at": row.created_at.isoformat() if row.created_at else None,
                    "updated_at": row.updated_at.isoformat() if row.updated_at else None,
                    "decisions": [
                        {
                            "id": item.id,
                            "title": item.title,
                            "decision": item.decision,
                            "gate_decision": item.gate_decision,
                            "risk_class": item.risk_class,
                            "blast_radius": item.blast_radius,
                            "options_considered": item.options_considered,
                        }
                        for item in decisions
                    ],
                }
            )
        return result


def persist_decisions(
    *,
    run_id: str,
    project_id: str,
    decisions: list[dict[str, Any]],
    environment: str = "prod",
) -> list[dict[str, Any]]:
    """Write ADRs, findings, and engineering memory. Returns gated decision dicts."""
    if not decisions:
        return []
    workflow_id = ensure_architect_workflow(project_id)
    wf_run = store.create_run(workflow_id, trigger="manual")
    workflow_run_id = (wf_run or {}).get("id") or str(uuid.uuid4())
    store.mark_run_running(workflow_run_id)

    findings: list[dict[str, Any]] = []
    gated: list[dict[str, Any]] = []
    with SessionLocal() as session:
        for item in decisions:
            risk_class = item.get("risk_class") or "config_code_change"
            blast = item.get("blast_radius") or "medium"
            gate = risk_engine.classify(risk_class, blast, environment)  # type: ignore[arg-type]
            decision_id = str(uuid.uuid4())
            session.add(
                ArchitectureDecision(
                    id=decision_id,
                    run_id=run_id,
                    title=(item.get("title") or "Architecture decision")[:400],
                    context=item.get("context") or "",
                    options_considered=item.get("options_considered") or [],
                    decision=item.get("decision") or "",
                    consequences=item.get("consequences") or "",
                    risk_summary=gate.rationale,
                    risk_class=risk_class,
                    blast_radius=blast,
                    gate_decision=gate.gate,
                )
            )
            session.add(
                EngineeringMemory(
                    id=str(uuid.uuid4()),
                    project_id=project_id,
                    kind="architecture_decision",
                    ref_id=decision_id,
                    summary=item.get("title") or item.get("decision") or "ADR",
                    outcome="proposed",
                    payload={
                        "skill": "solution_architect",
                        "module": "architecture",
                        "risk_class": risk_class,
                        "blast_radius": blast,
                        "gate": gate.gate,
                        "options_considered": item.get("options_considered") or [],
                    },
                )
            )
            gated.append({**item, "id": decision_id, "gate": gate.gate, "gate_label": gate.label})
            if item.get("decision") or item.get("recommended_action"):
                findings.append(
                    {
                        "skill": "solution_architect",
                        "module": "architecture",
                        "severity": item.get("severity") or ("high" if gate.two_person else "medium"),
                        "title": item.get("title") or "Architecture change",
                        "resource": item.get("resource") or "architecture",
                        "category": "architecture",
                        "evidence": item.get("context") or "",
                        "recommended_action": item.get("recommended_action") or item.get("decision") or "",
                        "risk_class": risk_class,
                        "blast_radius": blast,
                        "gate_decision": gate.gate,
                        "gate_label": gate.label,
                        "gate_rationale": gate.rationale,
                    }
                )
        session.commit()

    count = store.save_findings(workflow_run_id, workflow_id, project_id, findings)
    store.mark_run_succeeded(workflow_run_id, count)
    return gated


def high_gate_unjustified(candidates: list[dict[str, Any]], environment: str = "prod") -> bool:
    for item in candidates:
        if not item.get("recommended"):
            continue
        gate = risk_engine.classify(
            item.get("risk_class") or "config_code_change",  # type: ignore[arg-type]
            item.get("blast_radius") or "high",  # type: ignore[arg-type]
            environment,  # type: ignore[arg-type]
        )
        if gate.gate in HIGH_GATES and not item.get("justified"):
            return True
    return False
