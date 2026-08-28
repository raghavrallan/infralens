"""Workflow, run and finding persistence for the Intelligence Layer.

Workflows group one or more read-only diagnose skills that run together, on a
schedule or on demand. Every run is tracked from queued to finished, and each
finding it produces carries the Risk Engine gate decided at write time. Findings
are grouped under the six agent modules from the design.
"""
import uuid
from datetime import date, datetime, time, timedelta, timezone
from typing import Any, Optional

from sqlalchemy import delete, func, select

from app.core.db import (
    DEFAULT_PROJECT_ID,
    Approval,
    EngineeringMemory,
    Finding,
    FindingIdentity,
    SessionLocal,
    Workflow,
    WorkflowRun,
)
from app.intelligence.findings import compute_fingerprint
from app.intelligence.risk_engine import GATE_LABELS as _GATE_LABELS
from app.skills.classification import is_workflow_safe

# Change-producing findings wait this long for a decision; nothing auto-executes.
_APPROVAL_TTL_HOURS = 72
_APPROVAL_GATES = ("human_approval", "two_person")
# RQ jobs time out at 900s; anything still queued/running after this is a zombie.
STALE_RUN_AFTER = timedelta(minutes=30)
STALE_RUN_ERROR = (
    "Timed out — this run never finished. The worker likely crashed or the job was killed."
)
TIME_RANGE_DURATIONS = {
    "24h": timedelta(hours=24),
    "7d": timedelta(days=7),
    "30d": timedelta(days=30),
    "90d": timedelta(days=90),
}

# The six agent modules from the design, each backed by diagnose skills.
MODULES: dict[str, dict[str, Any]] = {
    "pipeline_intelligence": {
        "label": "Pipeline Intelligence",
        "description": (
            "Inspect CI/CD pipelines and application code for delivery, dependency, "
            "and engineering-quality risks before release."
        ),
        "skills": ["pipeline_auditor", "code_reviewer"],
    },
    "release_confidence": {
        "label": "Release Confidence",
        "description": (
            "Combine service metrics, logs, and reporting to judge release health, "
            "stability, and operational readiness."
        ),
        "skills": ["metrics_analyzer", "log_analyzer", "report_writer"],
    },
    "iac": {
        "label": "Infrastructure as Code",
        "description": (
            "Compare live cloud resources with infrastructure code to detect drift "
            "and missing guardrails."
        ),
        "skills": ["drift_auditor", "iac_reviewer"],
    },
    "incident_response": {
        "label": "Incident Response",
        "description": (
            "Correlate logs, metrics, and incident signals to identify likely causes "
            "and guide response."
        ),
        "skills": ["log_analyzer", "metrics_analyzer", "incident_analyzer"],
    },
    "security_patch": {
        "label": "Security & Patch",
        "description": (
            "Prioritize vulnerabilities and map security evidence to remediation "
            "and compliance controls."
        ),
        "skills": ["vuln_triage", "compliance_mapper"],
    },
    "finops": {
        "label": "FinOps",
        "description": (
            "Analyze cloud spend and utilization to surface anomalies and "
            "rightsizing opportunities."
        ),
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


def _as_utc(value: Optional[datetime]) -> Optional[datetime]:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def time_range_bounds(
    time_range: str = "all",
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
) -> tuple[Optional[datetime], Optional[datetime]]:
    """Return inclusive UTC date bounds for a preset or custom range."""
    if start_date is not None or end_date is not None or time_range == "custom":
        since = (
            datetime.combine(start_date, time.min, tzinfo=timezone.utc)
            if start_date is not None
            else None
        )
        until = (
            datetime.combine(end_date + timedelta(days=1), time.min, tzinfo=timezone.utc)
            if end_date is not None
            else None
        )
        return since, until
    duration = TIME_RANGE_DURATIONS.get((time_range or "all").lower())
    return (_now() - duration if duration else None), None


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


def _finding_dict(
    row: Finding,
    identity: FindingIdentity | None = None,
) -> dict[str, Any]:
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
        "fingerprint": identity.fingerprint if identity else None,
        "occurrence_count": identity.occurrence_count if identity else 1,
        "last_seen_at": _iso(identity.last_seen_at) if identity else _iso(row.created_at),
    }


# ---------- Workflows ----------

def list_workflows(project_id: str, module: Optional[str] = None) -> list[dict[str, Any]]:
    with SessionLocal() as session:
        filters = [Workflow.project_id == project_id]
        if module:
            filters.append(Workflow.module == module)
        rows = list(
            session.execute(
                select(Workflow)
                .where(*filters)
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
                    # Disabled until a cloud provider is connected for the project.
                    enabled=False,
                )
            )
        session.commit()


def enable_workflows_when_ready(project_id: str) -> int:
    """Enable seeded workflows once Azure (or another cloud) is connected. Returns count."""
    from app.platform import connections

    azure = connections.status(project_id, "azure")
    aws = connections.status(project_id, "aws")
    if not (azure.get("connected") or aws.get("connected")):
        return 0
    with SessionLocal() as session:
        rows = list(
            session.scalars(
                select(Workflow).where(
                    Workflow.project_id == project_id,
                    Workflow.enabled.is_(False),
                )
            ).all()
        )
        enabled = 0
        for row in rows:
            if not (row.skills or []):
                continue
            row.enabled = True
            enabled += 1
        session.commit()
        return enabled


# ---------- Runs ----------

def reap_stale_runs(project_id: Optional[str] = None) -> int:
    """Fail queued/running workflow runs that outlived the worker timeout."""
    cutoff = _now() - STALE_RUN_AFTER
    closed = 0
    with SessionLocal() as session:
        filters = [WorkflowRun.status.in_(("queued", "running"))]
        if project_id:
            filters.append(WorkflowRun.project_id == project_id)
        rows = list(session.scalars(select(WorkflowRun).where(*filters)))
        for run in rows:
            stamp = _as_utc(run.started_at) or _as_utc(run.created_at)
            if stamp is None or stamp > cutoff:
                continue
            run.status = "failed"
            run.error = STALE_RUN_ERROR
            run.finished_at = _now()
            closed += 1
        if closed:
            session.commit()
    return closed


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


def list_runs(
    project_id: str,
    limit: int = 30,
    time_range: str = "all",
    module: Optional[str] = None,
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
) -> list[dict[str, Any]]:
    reap_stale_runs(project_id)
    since, until = time_range_bounds(time_range, start_date, end_date)
    with SessionLocal() as session:
        filters = [WorkflowRun.project_id == project_id]
        if since is not None:
            filters.append(WorkflowRun.created_at >= since)
        if until is not None:
            filters.append(WorkflowRun.created_at < until)
        if module:
            filters.append(Workflow.module == module)
        rows = session.execute(
            select(WorkflowRun, Workflow.name)
            .join(Workflow, Workflow.id == WorkflowRun.workflow_id, isouter=True)
            .where(*filters)
            .order_by(WorkflowRun.created_at.desc())
            .limit(limit)
        ).all()
        return [_run_dict(run, name or "") for run, name in rows]


# ---------- Findings ----------

def _apply_finding_fields(
    row: Finding,
    *,
    run_id: str,
    workflow_id: str,
    item: dict[str, Any],
) -> None:
    row.run_id = run_id
    row.workflow_id = workflow_id
    row.skill = item.get("skill", "") or row.skill
    row.module = item.get("module", "") or row.module
    row.severity = item.get("severity", row.severity) or "low"
    row.title = item.get("title", "") or row.title
    row.resource = item.get("resource", "") or row.resource
    row.category = item.get("category", "") or row.category
    row.evidence = item.get("evidence", "") or row.evidence
    row.recommended_action = (
        item.get("recommended_action", "") or row.recommended_action
    )
    row.risk_class = item.get("risk_class", row.risk_class) or "config_code_change"
    row.blast_radius = item.get("blast_radius", row.blast_radius) or "medium"
    row.gate_decision = item.get("gate_decision", row.gate_decision) or "human_approval"
    row.gate_label = item.get("gate_label", "") or row.gate_label
    row.gate_rationale = item.get("gate_rationale", "") or row.gate_rationale


def _ensure_pending_approval(
    session: Any,
    *,
    finding_id: str,
    project_id: str,
    gate: str,
) -> None:
    if gate not in _APPROVAL_GATES:
        return
    existing = session.scalar(
        select(Approval.id).where(
            Approval.finding_id == finding_id,
            Approval.decision == "pending",
        )
    )
    if existing:
        return
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


def collapse_duplicate_findings(project_id: str) -> int:
    """Hide historical clone rows for the same issue (older → resolved).

    Keeps the newest open/acknowledged finding per fingerprint and records
    occurrence counts on ``finding_identities``. Safe to call on every
    dashboard read — cheap when there are no duplicates.
    """
    with SessionLocal() as session:
        rows = list(
            session.execute(
                select(Finding)
                .where(
                    Finding.project_id == project_id,
                    Finding.status.in_(("open", "acknowledged")),
                )
                .order_by(Finding.created_at.desc())
            ).scalars()
        )
        keepers: dict[str, Finding] = {}
        counts: dict[str, int] = {}
        to_resolve: list[str] = []
        now = _now()
        for row in rows:
            fp = compute_fingerprint(
                project_id, row.skill or "", row.resource or "", row.title or ""
            )
            counts[fp] = counts.get(fp, 0) + 1
            if fp in keepers:
                to_resolve.append(row.id)
            else:
                keepers[fp] = row

        for offset in range(0, len(to_resolve), 150):
            chunk = to_resolve[offset : offset + 150]
            session.execute(
                Finding.__table__.update()
                .where(Finding.id.in_(chunk))
                .values(status="resolved")
            )

        existing_ids = {
            row.fingerprint: row
            for row in session.execute(
                select(FindingIdentity).where(FindingIdentity.project_id == project_id)
            ).scalars()
        }
        for fp, keeper in keepers.items():
            count = counts.get(fp, 1)
            identity = existing_ids.get(fp)
            if identity is None:
                session.add(
                    FindingIdentity(
                        fingerprint=fp,
                        project_id=project_id,
                        finding_id=keeper.id,
                        occurrence_count=count,
                        last_seen_at=keeper.created_at or now,
                    )
                )
            else:
                identity.finding_id = keeper.id
                identity.project_id = project_id
                if (identity.occurrence_count or 1) < count:
                    identity.occurrence_count = count
                if keeper.created_at and (
                    identity.last_seen_at is None
                    or keeper.created_at > identity.last_seen_at
                ):
                    identity.last_seen_at = keeper.created_at

        if to_resolve:
            # Drop pending approvals attached to collapsed clone rows.
            session.execute(
                Approval.__table__.update()
                .where(
                    Approval.finding_id.in_(to_resolve),
                    Approval.decision == "pending",
                )
                .values(decision="rejected", decided_by="system:dedupe")
            )

        session.commit()
        return len(to_resolve)


def save_findings(
    run_id: str, workflow_id: str, project_id: str, findings: list[dict[str, Any]]
) -> int:
    """Persist findings with upsert-by-fingerprint so reruns do not clone issues."""
    if not findings:
        return 0
    written = 0
    with SessionLocal() as session:
        for item in findings:
            title = item.get("title", "") or ""
            resource = item.get("resource", "") or ""
            skill = item.get("skill", "") or ""
            fp = compute_fingerprint(project_id, skill, resource, title)
            gate = item.get("gate_decision", "human_approval")
            identity = session.get(FindingIdentity, fp)
            existing = (
                session.get(Finding, identity.finding_id) if identity else None
            )

            if existing is not None:
                was_resolved = existing.status == "resolved"
                _apply_finding_fields(
                    existing, run_id=run_id, workflow_id=workflow_id, item=item
                )
                if was_resolved:
                    existing.status = "open"
                identity.finding_id = existing.id
                identity.occurrence_count = int(identity.occurrence_count or 1) + 1
                identity.last_seen_at = _now()
                _ensure_pending_approval(
                    session,
                    finding_id=existing.id,
                    project_id=project_id,
                    gate=gate,
                )
                written += 1
                continue

            finding_id = str(uuid.uuid4())
            session.add(
                Finding(
                    id=finding_id,
                    run_id=run_id,
                    workflow_id=workflow_id,
                    project_id=project_id,
                    skill=skill,
                    module=item.get("module", ""),
                    severity=item.get("severity", "low"),
                    title=title,
                    resource=resource,
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
            session.add(
                FindingIdentity(
                    fingerprint=fp,
                    project_id=project_id,
                    finding_id=finding_id,
                    occurrence_count=1,
                    last_seen_at=_now(),
                )
            )
            _ensure_pending_approval(
                session,
                finding_id=finding_id,
                project_id=project_id,
                gate=gate,
            )
            written += 1
        session.commit()
    return written


def _identity_map(session: Any, finding_ids: list[str]) -> dict[str, FindingIdentity]:
    if not finding_ids:
        return {}
    rows = session.execute(
        select(FindingIdentity).where(FindingIdentity.finding_id.in_(finding_ids))
    ).scalars()
    return {row.finding_id: row for row in rows}


def list_findings(
    project_id: str,
    severity: Optional[str] = None,
    skill: Optional[str] = None,
    module: Optional[str] = None,
    status: Optional[str] = None,
    limit: int = 100,
    time_range: str = "all",
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
) -> list[dict[str, Any]]:
    collapse_duplicate_findings(project_id)
    since, until = time_range_bounds(time_range, start_date, end_date)
    with SessionLocal() as session:
        query = select(Finding).where(Finding.project_id == project_id)
        if since is not None:
            query = query.where(Finding.created_at >= since)
        if until is not None:
            query = query.where(Finding.created_at < until)
        if severity:
            query = query.where(Finding.severity == severity)
        if skill:
            query = query.where(Finding.skill == skill)
        if module:
            query = query.where(Finding.module == module)
        if status:
            query = query.where(Finding.status == status)
        query = query.order_by(Finding.created_at.desc()).limit(limit)
        rows = list(session.execute(query).scalars())
        identities = _identity_map(session, [row.id for row in rows])
        return [_finding_dict(f, identities.get(f.id)) for f in rows]


def update_finding_status(finding_id: str, status: str) -> Optional[dict[str, Any]]:
    if status not in ("open", "acknowledged", "resolved"):
        return None
    with SessionLocal() as session:
        row = session.get(Finding, finding_id)
        if row is None:
            return None
        row.status = status
        session.commit()
        identity = session.scalar(
            select(FindingIdentity).where(FindingIdentity.finding_id == finding_id)
        )
        return _finding_dict(row, identity)


# ---------- Approvals ----------

def _approval_dict(
    approval: Approval,
    finding: Optional[Finding],
    *,
    break_glass_active: Optional[bool] = None,
    precedent: Optional[list[dict[str, Any]]] = None,
) -> dict[str, Any]:
    now = _now()
    expires = approval.expires_at
    expired = bool(expires and expires <= now and approval.decision == "pending")
    from app.platform import (
        break_glass,
        memory,
    )
    from app.core.rbac import GATE_MIN_ROLE, ROLE_LABELS

    gate = approval.gate
    bg = break_glass.gate_with_break_glass(
        gate, approval.project_id, active=break_glass_active
    )
    effective_gate = bg["gate"]
    if precedent is None:
        precedent = memory.list_precedent(
            approval.project_id,
            skill=finding.skill if finding else None,
            module=finding.module if finding else None,
            limit=5,
        )
    payload: dict[str, Any] = {
        "id": approval.id,
        "finding_id": approval.finding_id,
        "project_id": approval.project_id,
        "gate": effective_gate,
        "original_gate": gate,
        "gate_label": _GATE_LABELS.get(effective_gate, effective_gate),
        "gate_rationale": (finding.gate_rationale if finding else "") or "",
        "break_glass_applied": bg.get("break_glass_applied", False),
        "min_role": GATE_MIN_ROLE.get(effective_gate, "devops_lead"),
        "min_role_label": ROLE_LABELS.get(
            GATE_MIN_ROLE.get(effective_gate, "devops_lead"), "DevOps Lead"
        ),
        "decision": approval.decision,
        "decided_by": approval.decided_by,
        "created_at": _iso(approval.created_at),
        "expires_at": _iso(expires),
        "expired": expired,
        "expires_in_seconds": int((expires - now).total_seconds()) if expires else None,
        "blast_radius": finding.blast_radius if finding else "",
        "evidence": finding.evidence if finding else "",
        "recommended_action": finding.recommended_action if finding else "",
        "rollback": (finding.recommended_action if finding else "")
        or "Document rollback before approve",
        "preflight": {
            "summary": "Review evidence and recommended action before approving.",
            "checks": ["evidence reviewed", "blast radius understood", "rollback known"],
        },
        "precedent": precedent,
    }
    if finding is not None:
        payload["finding"] = _finding_dict(finding)
        if getattr(finding, "gate_rationale", None):
            payload["gate_rationale"] = finding.gate_rationale
    return payload


def list_approvals(
    project_id: str,
    status: str = "pending",
    limit: int = 100,
    module: Optional[str] = None,
    time_range: str = "all",
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
) -> list[dict[str, Any]]:
    """Approvals for a project, joined to their finding. Default: pending only."""
    from app.platform import (
        break_glass,
        memory,
    )

    since, until = time_range_bounds(time_range, start_date, end_date)
    # One break-glass lookup + one memory preload for the whole list (not per row).
    bg_active = break_glass.is_active(project_id)
    memory_rows = memory.list_recent(project_id, limit=50)
    with SessionLocal() as session:
        query = (
            select(Approval, Finding)
            .join(Finding, Finding.id == Approval.finding_id, isouter=True)
            .where(Approval.project_id == project_id)
        )
        if since is not None:
            query = query.where(Approval.created_at >= since)
        if until is not None:
            query = query.where(Approval.created_at < until)
        if module:
            query = query.where(Finding.module == module)
        if status and status != "all":
            query = query.where(Approval.decision == status)
        query = query.order_by(Approval.created_at.desc()).limit(limit)
        rows = list(session.execute(query).all())
        return [
            _approval_dict(
                a,
                f,
                break_glass_active=bg_active,
                precedent=memory.filter_precedent(
                    memory_rows,
                    skill=f.skill if f else None,
                    module=f.module if f else None,
                    limit=5,
                ),
            )
            for a, f in rows
        ]


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

def dashboard_summary(
    project_id: str,
    time_range: str = "all",
    module: Optional[str] = None,
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
) -> dict[str, Any]:
    collapse_duplicate_findings(project_id)
    reap_stale_runs(project_id)
    since, until = time_range_bounds(time_range, start_date, end_date)
    date_filter = []
    if module:
        date_filter.append(Finding.module == module)
    if since is not None:
        date_filter.append(Finding.created_at >= since)
    if until is not None:
        date_filter.append(Finding.created_at < until)
    approval_date_filter = []
    if since is not None:
        approval_date_filter.append(Approval.created_at >= since)
    if until is not None:
        approval_date_filter.append(Approval.created_at < until)
    workflow_date_filter = []
    if since is not None:
        workflow_date_filter.append(Workflow.created_at >= since)
    if until is not None:
        workflow_date_filter.append(Workflow.created_at < until)
    run_date_filter = []
    if since is not None:
        run_date_filter.append(WorkflowRun.created_at >= since)
    if until is not None:
        run_date_filter.append(WorkflowRun.created_at < until)
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

        approval_filter = [
            Approval.project_id == project_id,
            Approval.decision == "pending",
            *approval_date_filter,
        ]
        if module:
            approval_filter.append(
                Approval.finding_id.in_(
                    select(Finding.id).where(
                        Finding.project_id == project_id, Finding.module == module
                    )
                )
            )
        pending_approvals = (
            select(func.count())
            .select_from(Approval)
            .where(*approval_filter)
            .scalar_subquery()
        )
        workflow_filter = [Workflow.project_id == project_id]
        if module:
            workflow_filter.append(Workflow.module == module)
        workflow_total = (
            select(func.count())
            .select_from(Workflow)
            .where(*workflow_filter)
            .where(*workflow_date_filter)
            .scalar_subquery()
        )
        workflow_enabled = (
            select(func.count())
            .select_from(Workflow)
            .where(*workflow_filter, Workflow.enabled.is_(True))
            .where(*workflow_date_filter)
            .scalar_subquery()
        )
        run_counts = {
            status: (
                select(func.count())
                .select_from(WorkflowRun)
                .where(
                    WorkflowRun.project_id == project_id,
                    WorkflowRun.status == status,
                    *(
                        [
                            WorkflowRun.workflow_id.in_(
                                select(Workflow.id).where(*workflow_filter)
                            )
                        ]
                        if module
                        else []
                    ),
                )
                .where(*run_date_filter)
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
        ).select_from(Finding).where(
            Finding.project_id == project_id,
            *date_filter,
        )
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
