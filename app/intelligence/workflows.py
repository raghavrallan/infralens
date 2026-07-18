"""Workflow, run and finding persistence for the Intelligence Layer.

Workflows group one or more read-only diagnose skills that run together, on a
schedule or on demand. Every run is tracked from queued to finished, and each
finding it produces carries the Risk Engine gate decided at write time. Findings
are grouped under the six agent modules from the design.
"""
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from sqlalchemy import delete, func, select

from app.db import (
    DEFAULT_PROJECT_ID,
    Approval,
    EngineeringMemory,
    Finding,
    SessionLocal,
    Workflow,
    WorkflowRun,
)
from app.intelligence.risk_engine import GATE_LABELS as _GATE_LABELS
from app.skills import is_workflow_safe

# Change-producing findings wait this long for a decision; nothing auto-executes.
_APPROVAL_TTL_HOURS = 72
_APPROVAL_GATES = ("human_approval", "two_person")

# The six agent modules from the design, each backed by diagnose skills.
MODULES: dict[str, dict[str, Any]] = {
    "pipeline_intelligence": {
        "label": "Pipeline Intelligence",
        "skills": ["pipeline_auditor", "code_reviewer"],
    },
    "release_confidence": {
        "label": "Release Confidence",
        "skills": ["metrics_analyzer", "log_analyzer", "report_writer"],
    },
    "iac": {
        "label": "Infrastructure as Code",
        "skills": ["drift_auditor", "iac_reviewer"],
    },
    "incident_response": {
        "label": "Incident Response",
        "skills": ["log_analyzer", "metrics_analyzer", "incident_analyzer"],
    },
    "security_patch": {
        "label": "Security & Patch",
        "skills": ["vuln_triage", "compliance_mapper"],
    },
    "finops": {
        "label": "FinOps",
        "skills": ["cost_analyzer", "metrics_analyzer"],
    },
}

_DEFAULT_WORKFLOWS: tuple[dict[str, Any], ...] = (
    {
        "name": "Nightly Posture Sweep",
        "module": "iac",
        "objective": (
            "Review the connected cloud posture and compare live infrastructure "
            "against the infrastructure code to surface drift and missing guardrails."
        ),
        "skills": ["cloud_posture", "drift_auditor", "iac_reviewer"],
        "schedule_cron": "0 2 * * *",
    },
    {
        "name": "Security & Patch Watch",
        "module": "security_patch",
        "objective": (
            "Triage scanner findings and map controls to compliance frameworks to "
            "surface unpatched, high-risk exposure."
        ),
        "skills": ["vuln_triage", "compliance_mapper"],
        "schedule_cron": "0 */6 * * *",
    },
    {
        "name": "Reliability & Error Watch",
        "module": "incident_response",
        "objective": (
            "Check request error rates and resource metrics for the connected apps "
            "and flag anomalies worth investigating."
        ),
        "skills": ["log_analyzer", "metrics_analyzer"],
        "schedule_cron": "0 * * * *",
    },
    {
        "name": "Cost Anomaly Watch",
        "module": "finops",
        "objective": (
            "Review recent cloud spend and utilization to surface cost anomalies "
            "and rightsizing opportunities."
        ),
        "skills": ["cost_analyzer", "metrics_analyzer"],
        "schedule_cron": "0 7 * * *",
    },
)


def _iso(value: Optional[datetime]) -> Optional[str]:
    return value.isoformat() if value else None


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _safe_skills(skills: list[str]) -> list[str]:
    """Keep only registered, workflow-safe (read-only) skills."""
    seen: list[str] = []
    for name in skills:
        if is_workflow_safe(name) and name not in seen:
            seen.append(name)
    return seen


def _module_of(skills: list[str]) -> str:
    for key, spec in MODULES.items():
        if any(skill in spec["skills"] for skill in skills):
            return key
    return ""


def _workflow_dict(row: Workflow) -> dict[str, Any]:
    return {
        "id": row.id,
        "project_id": row.project_id,
        "name": row.name,
        "objective": row.objective,
        "module": row.module,
        "module_label": MODULES.get(row.module, {}).get("label", ""),
        "environment": row.environment,
        "skills": list(row.skills or []),
        "schedule_cron": row.schedule_cron,
        "enabled": row.enabled,
        "created_at": _iso(row.created_at),
        "updated_at": _iso(row.updated_at),
    }


def _run_dict(row: WorkflowRun, workflow_name: str = "") -> dict[str, Any]:
    return {
        "id": row.id,
        "workflow_id": row.workflow_id,
        "workflow_name": workflow_name,
        "project_id": row.project_id,
        "status": row.status,
        "trigger": row.trigger,
        "finding_count": row.finding_count,
        "error": row.error,
        "created_at": _iso(row.created_at),
        "started_at": _iso(row.started_at),
        "finished_at": _iso(row.finished_at),
    }


def _finding_dict(row: Finding) -> dict[str, Any]:
    return {
        "id": row.id,
        "run_id": row.run_id,
        "workflow_id": row.workflow_id,
        "project_id": row.project_id,
        "skill": row.skill,
        "module": row.module,
        "module_label": MODULES.get(row.module, {}).get("label", ""),
        "severity": row.severity,
        "title": row.title,
        "resource": row.resource,
        "category": row.category,
        "evidence": row.evidence,
        "recommended_action": row.recommended_action,
        "risk_class": row.risk_class,
        "blast_radius": row.blast_radius,
        "gate_decision": row.gate_decision,
        "gate_label": row.gate_label,
        "gate_rationale": row.gate_rationale,
        "status": row.status,
        "created_at": _iso(row.created_at),
    }


# ---------- Workflows ----------

def list_workflows(project_id: str) -> list[dict[str, Any]]:
    with SessionLocal() as session:
        rows = list(
            session.execute(
                select(Workflow)
                .where(Workflow.project_id == project_id)
                .order_by(Workflow.created_at.asc())
            ).scalars()
        )
        run_rows = session.execute(
            select(WorkflowRun)
            .where(WorkflowRun.project_id == project_id)
            .order_by(WorkflowRun.created_at.desc())
        ).scalars()
        latest: dict[str, WorkflowRun] = {}
        for run in run_rows:
            latest.setdefault(run.workflow_id, run)
        result = []
        for workflow in rows:
            data = _workflow_dict(workflow)
            run = latest.get(workflow.id)
            data["last_run"] = (
                {
                    "status": run.status,
                    "created_at": _iso(run.created_at),
                    "finding_count": run.finding_count,
                }
                if run
                else None
            )
            result.append(data)
        return result


def get_workflow(workflow_id: str) -> Optional[dict[str, Any]]:
    with SessionLocal() as session:
        row = session.get(Workflow, workflow_id)
        return _workflow_dict(row) if row else None


def create_workflow(
    project_id: str,
    name: str,
    skills: list[str],
    objective: str = "",
    module: str = "",
    environment: str = "prod",
    schedule_cron: str = "",
    enabled: bool = True,
) -> dict[str, Any]:
    safe = _safe_skills(skills)
    with SessionLocal() as session:
        row = Workflow(
            id=str(uuid.uuid4()),
            project_id=project_id,
            name=(name or "New workflow").strip(),
            objective=objective.strip(),
            module=module or _module_of(safe),
            environment=environment if environment in ("dev", "staging", "prod") else "prod",
            skills=safe,
            schedule_cron=schedule_cron.strip(),
            enabled=enabled,
        )
        session.add(row)
        session.commit()
        return _workflow_dict(row)


def update_workflow(workflow_id: str, **fields: Any) -> Optional[dict[str, Any]]:
    with SessionLocal() as session:
        row = session.get(Workflow, workflow_id)
        if row is None:
            return None
        if "name" in fields and fields["name"]:
            row.name = str(fields["name"]).strip()
        if "objective" in fields:
            row.objective = str(fields["objective"] or "").strip()
        if "skills" in fields and fields["skills"] is not None:
            row.skills = _safe_skills(list(fields["skills"]))
            row.module = fields.get("module") or _module_of(row.skills)
        elif "module" in fields and fields["module"]:
            row.module = str(fields["module"])
        if "environment" in fields and fields["environment"] in ("dev", "staging", "prod"):
            row.environment = fields["environment"]
        if "schedule_cron" in fields:
            row.schedule_cron = str(fields["schedule_cron"] or "").strip()
        if "enabled" in fields and fields["enabled"] is not None:
            row.enabled = bool(fields["enabled"])
        session.commit()
        return _workflow_dict(row)


def delete_workflow(workflow_id: str) -> bool:
    with SessionLocal() as session:
        row = session.get(Workflow, workflow_id)
        if row is None:
            return False
        run_ids = list(
            session.execute(
                select(WorkflowRun.id).where(WorkflowRun.workflow_id == workflow_id)
            ).scalars()
        )
        if run_ids:
            session.execute(delete(Finding).where(Finding.run_id.in_(run_ids)))
        session.execute(delete(WorkflowRun).where(WorkflowRun.workflow_id == workflow_id))
        session.delete(row)
        session.commit()
        return True


def seed_default_workflows(project_id: str = DEFAULT_PROJECT_ID) -> None:
    """Create the starter workflows for a project if it has none yet."""
    with SessionLocal() as session:
        existing = session.execute(
            select(func.count()).select_from(Workflow).where(
                Workflow.project_id == project_id
            )
        ).scalar_one()
        if existing:
            return
        for spec in _DEFAULT_WORKFLOWS:
            session.add(
                Workflow(
                    id=str(uuid.uuid4()),
                    project_id=project_id,
                    name=spec["name"],
                    objective=spec["objective"],
                    module=spec["module"],
                    environment="prod",
                    skills=_safe_skills(spec["skills"]),
                    schedule_cron=spec["schedule_cron"],
                    enabled=True,
                )
            )
        session.commit()


# ---------- Runs ----------

def create_run(workflow_id: str, trigger: str = "manual") -> Optional[dict[str, Any]]:
    with SessionLocal() as session:
        workflow = session.get(Workflow, workflow_id)
        if workflow is None:
            return None
        run = WorkflowRun(
            id=str(uuid.uuid4()),
            workflow_id=workflow_id,
            project_id=workflow.project_id,
            status="queued",
            trigger=trigger,
        )
        session.add(run)
        session.commit()
        return _run_dict(run, workflow.name)


def mark_run_running(run_id: str) -> None:
    with SessionLocal() as session:
        run = session.get(WorkflowRun, run_id)
        if run is not None:
            run.status = "running"
            run.started_at = _now()
            session.commit()


def mark_run_succeeded(run_id: str, finding_count: int) -> None:
    with SessionLocal() as session:
        run = session.get(WorkflowRun, run_id)
        if run is not None:
            run.status = "succeeded"
            run.finding_count = finding_count
            run.finished_at = _now()
            session.commit()


def mark_run_failed(run_id: str, error: str) -> None:
    with SessionLocal() as session:
        run = session.get(WorkflowRun, run_id)
        if run is not None:
            run.status = "failed"
            run.error = error[:2000]
            run.finished_at = _now()
            session.commit()


def get_run(run_id: str) -> Optional[dict[str, Any]]:
    with SessionLocal() as session:
        run = session.get(WorkflowRun, run_id)
        if run is None:
            return None
        workflow = session.get(Workflow, run.workflow_id)
        payload = _run_dict(run, workflow.name if workflow else "")
        findings = session.execute(
            select(Finding)
            .where(Finding.run_id == run_id)
            .order_by(Finding.created_at.asc())
        ).scalars()
        payload["findings"] = [_finding_dict(f) for f in findings]
        return payload


def list_runs(project_id: str, limit: int = 30) -> list[dict[str, Any]]:
    with SessionLocal() as session:
        rows = session.execute(
            select(WorkflowRun, Workflow.name)
            .join(Workflow, Workflow.id == WorkflowRun.workflow_id, isouter=True)
            .where(WorkflowRun.project_id == project_id)
            .order_by(WorkflowRun.created_at.desc())
            .limit(limit)
        ).all()
        return [_run_dict(run, name or "") for run, name in rows]


# ---------- Findings ----------

def save_findings(
    run_id: str, workflow_id: str, project_id: str, findings: list[dict[str, Any]]
) -> int:
    if not findings:
        return 0
    with SessionLocal() as session:
        for item in findings:
            finding_id = str(uuid.uuid4())
            gate = item.get("gate_decision", "human_approval")
            session.add(
                Finding(
                    id=finding_id,
                    run_id=run_id,
                    workflow_id=workflow_id,
                    project_id=project_id,
                    skill=item.get("skill", ""),
                    module=item.get("module", ""),
                    severity=item.get("severity", "low"),
                    title=item.get("title", ""),
                    resource=item.get("resource", ""),
                    category=item.get("category", ""),
                    evidence=item.get("evidence", ""),
                    recommended_action=item.get("recommended_action", ""),
                    risk_class=item.get("risk_class", "config_code_change"),
                    blast_radius=item.get("blast_radius", "medium"),
                    gate_decision=gate,
                    gate_label=item.get("gate_label", ""),
                    gate_rationale=item.get("gate_rationale", ""),
                    status="open",
                )
            )
            if gate in _APPROVAL_GATES:
                session.add(
                    Approval(
                        id=str(uuid.uuid4()),
                        finding_id=finding_id,
                        project_id=project_id,
                        gate=gate,
                        decision="pending",
                        expires_at=_now() + timedelta(hours=_APPROVAL_TTL_HOURS),
                    )
                )
        session.commit()
    return len(findings)


def list_findings(
    project_id: str,
    severity: Optional[str] = None,
    skill: Optional[str] = None,
    module: Optional[str] = None,
    status: Optional[str] = None,
    limit: int = 100,
) -> list[dict[str, Any]]:
    with SessionLocal() as session:
        query = select(Finding).where(Finding.project_id == project_id)
        if severity:
            query = query.where(Finding.severity == severity)
        if skill:
            query = query.where(Finding.skill == skill)
        if module:
            query = query.where(Finding.module == module)
        if status:
            query = query.where(Finding.status == status)
        query = query.order_by(Finding.created_at.desc()).limit(limit)
        return [_finding_dict(f) for f in session.execute(query).scalars()]


def update_finding_status(finding_id: str, status: str) -> Optional[dict[str, Any]]:
    if status not in ("open", "acknowledged", "resolved"):
        return None
    with SessionLocal() as session:
        row = session.get(Finding, finding_id)
        if row is None:
            return None
        row.status = status
        session.commit()
        return _finding_dict(row)


# ---------- Approvals ----------

def _approval_dict(approval: Approval, finding: Optional[Finding]) -> dict[str, Any]:
    now = _now()
    expires = approval.expires_at
    expired = bool(expires and expires <= now and approval.decision == "pending")
    payload: dict[str, Any] = {
        "id": approval.id,
        "finding_id": approval.finding_id,
        "project_id": approval.project_id,
        "gate": approval.gate,
        "gate_label": _GATE_LABELS.get(approval.gate, approval.gate),
        "decision": approval.decision,
        "decided_by": approval.decided_by,
        "created_at": _iso(approval.created_at),
        "expires_at": _iso(expires),
        "expired": expired,
        "expires_in_seconds": int((expires - now).total_seconds()) if expires else None,
    }
    if finding is not None:
        payload["finding"] = _finding_dict(finding)
    return payload


def list_approvals(
    project_id: str, status: str = "pending", limit: int = 100
) -> list[dict[str, Any]]:
    """Approvals for a project, joined to their finding. Default: pending only."""
    with SessionLocal() as session:
        query = (
            select(Approval, Finding)
            .join(Finding, Finding.id == Approval.finding_id, isouter=True)
            .where(Approval.project_id == project_id)
        )
        if status and status != "all":
            query = query.where(Approval.decision == status)
        query = query.order_by(Approval.created_at.desc()).limit(limit)
        return [_approval_dict(a, f) for a, f in session.execute(query).all()]


def decide_approval(
    approval_id: str, decision: str, decided_by: str = ""
) -> Optional[dict[str, Any]]:
    """Record an approve/reject decision and mark the finding accordingly.

    Approving records intent (the finding is acknowledged) and rejecting closes
    it (resolved). Nothing is executed — the decision is stored as precedent in
    engineering memory. The safe default on timeout is that nothing happens.
    """
    if decision not in ("approved", "rejected"):
        return None
    with SessionLocal() as session:
        approval = session.get(Approval, approval_id)
        if approval is None:
            return None
        approval.decision = decision
        approval.decided_by = (decided_by or "operator").strip()[:120]

        finding = session.get(Finding, approval.finding_id)
        if finding is not None:
            finding.status = "acknowledged" if decision == "approved" else "resolved"
            session.add(
                EngineeringMemory(
                    id=str(uuid.uuid4()),
                    project_id=approval.project_id,
                    kind="approval",
                    ref_id=finding.id,
                    summary=finding.title,
                    outcome=decision,
                    payload={
                        "skill": finding.skill,
                        "module": finding.module,
                        "severity": finding.severity,
                        "resource": finding.resource,
                        "gate": approval.gate,
                        "blast_radius": finding.blast_radius,
                        "recommended_action": finding.recommended_action,
                        "decided_by": approval.decided_by,
                    },
                )
            )
        session.commit()
        return _approval_dict(approval, finding)


def _pending_approvals(session: Any, project_id: str) -> int:
    return session.execute(
        select(func.count())
        .select_from(Approval)
        .where(Approval.project_id == project_id, Approval.decision == "pending")
    ).scalar_one()


# ---------- Dashboard ----------

def dashboard_summary(project_id: str) -> dict[str, Any]:
    with SessionLocal() as session:
        # Conditional aggregates keep the dashboard count payload to one DB
        # round-trip instead of one query per tile/filter group.
        active = Finding.status != "resolved"
        finding_count_columns = (
            func.count(Finding.id).filter(active).label("open_total"),
            func.count(Finding.id)
            .filter(active, Finding.severity == "critical")
            .label("critical"),
            func.count(Finding.id)
            .filter(active, Finding.severity == "high")
            .label("high"),
            func.count(Finding.id)
            .filter(active, Finding.severity == "medium")
            .label("medium"),
            func.count(Finding.id)
            .filter(active, Finding.severity == "low")
            .label("low"),
            func.count(Finding.id)
            .filter(active, Finding.gate_decision == "human_approval")
            .label("human_approval"),
            func.count(Finding.id)
            .filter(active, Finding.gate_decision == "two_person")
            .label("two_person"),
        )

        pending_approvals = (
            select(func.count())
            .select_from(Approval)
            .where(Approval.project_id == project_id, Approval.decision == "pending")
            .scalar_subquery()
        )
        workflow_total = (
            select(func.count())
            .select_from(Workflow)
            .where(Workflow.project_id == project_id)
            .scalar_subquery()
        )
        workflow_enabled = (
            select(func.count())
            .select_from(Workflow)
            .where(Workflow.project_id == project_id, Workflow.enabled.is_(True))
            .scalar_subquery()
        )
        run_counts = {
            status: (
                select(func.count())
                .select_from(WorkflowRun)
                .where(
                    WorkflowRun.project_id == project_id,
                    WorkflowRun.status == status,
                )
                .scalar_subquery()
            )
            for status in ("queued", "running", "succeeded", "failed")
        }
        dashboard_counts = session.execute(
            select(
                *finding_count_columns,
                workflow_total.label("workflow_total"),
                workflow_enabled.label("workflow_enabled"),
                pending_approvals.label("pending_approvals"),
                *(value.label(f"runs_{status}") for status, value in run_counts.items()),
            ).select_from(Finding).where(Finding.project_id == project_id)
        ).one()._mapping
        by_severity = {
            severity: int(dashboard_counts[severity])
            for severity in ("critical", "high", "medium", "low")
        }
        open_total = int(dashboard_counts["open_total"])
        by_gate = {
            gate: int(dashboard_counts[gate])
            for gate in ("human_approval", "two_person")
        }
        needs_approval = by_gate.get("human_approval", 0) + by_gate.get("two_person", 0)
        workflow_total = int(dashboard_counts["workflow_total"])
        workflow_enabled = int(dashboard_counts["workflow_enabled"])
        pending_approval_count = int(dashboard_counts["pending_approvals"])
        runs_by_status = {
            status: int(dashboard_counts[f"runs_{status}"])
            for status in run_counts
            if dashboard_counts[f"runs_{status}"]
        }

    return {
        "open_findings": open_total,
        "findings_by_severity": by_severity,
        "findings_by_gate": by_gate,
        "needs_approval": needs_approval,
        "pending_approvals": pending_approval_count,
        "workflows_total": workflow_total,
        "workflows_enabled": workflow_enabled,
        "runs_by_status": runs_by_status,
    }


def scheduled_workflows() -> list[dict[str, Any]]:
    """Every enabled workflow that has a cron schedule, across all projects."""
    with SessionLocal() as session:
        rows = session.execute(
            select(Workflow).where(
                Workflow.enabled.is_(True), Workflow.schedule_cron != ""
            )
        ).scalars()
        return [_workflow_dict(w) for w in rows]
