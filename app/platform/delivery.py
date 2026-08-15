"""E2E delivery runs: docs → architecture → terraform → plan → apply → code."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import select

from app.core.db import DeliveryRun, SessionLocal
from app.core.rbac import has_min_role

STAGES: tuple[str, ...] = (
    "ingest",
    "architecture",
    "terraform",
    "plan",
    "apply",
    "code",
    "done",
)

STAGE_MIN_ROLE: dict[str, str] = {
    "ingest": "developer",
    "architecture": "developer",
    "terraform": "devops_engineer",
    "plan": "devops_engineer",
    "apply": "devops_lead",
    "code": "developer",
    "done": "developer",
}

# Accepting architecture before TF/apply path requires Lead+.
ARCHITECTURE_ACCEPT_MIN_ROLE = "devops_lead"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: Optional[datetime]) -> Optional[str]:
    return value.isoformat() if value else None


def _dict(row: DeliveryRun) -> dict[str, Any]:
    artifacts = dict(row.artifacts or {})
    stage_index = STAGES.index(row.stage) if row.stage in STAGES else 0
    checklist = []
    for idx, stage in enumerate(STAGES[:-1]):  # exclude terminal done
        if idx < stage_index:
            state = "done"
        elif idx == stage_index:
            state = "current"
        else:
            state = "pending"
        checklist.append(
            {
                "stage": stage,
                "label": stage.replace("_", " ").title(),
                "status": state,
                "min_role": STAGE_MIN_ROLE.get(stage, "developer"),
            }
        )
    next_actions: list[str] = []
    if row.stage == "ingest":
        next_actions.append("Paste or upload requirements docs")
    elif row.stage == "architecture":
        next_actions.append("Review architecture proposal and accept (Lead+)")
    elif row.stage == "terraform":
        next_actions.append("Generate Terraform PR/bundle (never silent apply)")
    elif row.stage == "plan":
        next_actions.append("Review plan ActionDiff + rollback")
    elif row.stage == "apply":
        next_actions.append("Gated infra apply (prod needs Lead+)")
    elif row.stage == "code":
        next_actions.append("Scaffold app code PR")
    return {
        "id": row.id,
        "project_id": row.project_id,
        "stage": row.stage,
        "status": row.status,
        "artifacts": artifacts,
        "approved_by": row.approved_by,
        "created_by": row.created_by,
        "created_at": _iso(row.created_at),
        "updated_at": _iso(row.updated_at),
        "checklist": checklist,
        "next_actions": next_actions,
        "stages": list(STAGES),
    }


def create_run(project_id: str, *, created_by: str = "") -> dict[str, Any]:
    with SessionLocal() as session:
        row = DeliveryRun(
            id=str(uuid.uuid4()),
            project_id=project_id,
            stage="ingest",
            status="active",
            artifacts={},
            created_by=(created_by or "")[:120],
        )
        session.add(row)
        session.commit()
        session.refresh(row)
        return _dict(row)


def get_run(run_id: str) -> Optional[dict[str, Any]]:
    with SessionLocal() as session:
        row = session.get(DeliveryRun, run_id)
        return _dict(row) if row else None


def list_runs(project_id: str, limit: int = 20) -> list[dict[str, Any]]:
    with SessionLocal() as session:
        rows = session.scalars(
            select(DeliveryRun)
            .where(DeliveryRun.project_id == project_id)
            .order_by(DeliveryRun.created_at.desc())
            .limit(limit)
        ).all()
        return [_dict(r) for r in rows]


def _require_stage_role(user_role: str, stage: str) -> None:
    minimum = STAGE_MIN_ROLE.get(stage, "developer")
    if not has_min_role(user_role, minimum):
        raise PermissionError(f"Stage '{stage}' requires {minimum} or above")


def transition(
    run_id: str,
    *,
    to_stage: str,
    user_role: str,
    artifact_key: Optional[str] = None,
    artifact_value: Any = None,
    approved_by: str = "",
) -> dict[str, Any]:
    if to_stage not in STAGES:
        raise ValueError(f"Unknown stage: {to_stage}")
    _require_stage_role(user_role, to_stage)
    if to_stage == "architecture" and artifact_key == "architecture_accepted":
        if not has_min_role(user_role, ARCHITECTURE_ACCEPT_MIN_ROLE):
            raise PermissionError("Accepting architecture requires DevOps Lead or above")
    if to_stage == "apply" and not has_min_role(user_role, "devops_lead"):
        # Prod apply gate: Lead+ always for MVP apply stage.
        raise PermissionError("Infra apply requires DevOps Lead or above")

    with SessionLocal() as session:
        row = session.get(DeliveryRun, run_id)
        if row is None:
            raise LookupError("Delivery run not found")
        if row.status != "active":
            raise ValueError("Delivery run is not active")
        current_idx = STAGES.index(row.stage) if row.stage in STAGES else 0
        target_idx = STAGES.index(to_stage)
        if target_idx > current_idx + 1:
            raise ValueError("Cannot skip delivery stages")
        if target_idx < current_idx:
            raise ValueError("Cannot move delivery stage backwards")

        artifacts = dict(row.artifacts or {})
        if artifact_key:
            artifacts[artifact_key] = artifact_value
        if to_stage == "architecture" and "architecture_proposal" not in artifacts:
            artifacts["architecture_status"] = "generating"
            artifacts["architecture_proposal"] = {
                "summary": "Generating architecture from ingested requirements…",
                "components": [],
                "notes": str(artifacts.get("docs") or artifacts.get("requirements") or "")[:2000],
                "accepted": False,
            }
            row.artifacts = artifacts
            row.stage = to_stage
            row.updated_at = _now()
            session.commit()
            session.refresh(row)
            payload = _dict(row)
            _enqueue_architecture_job(run_id)
            return payload
        if to_stage == "terraform" and "terraform_pr" not in artifacts:
            artifacts["terraform_pr"] = {
                "status": "proposed",
                "title": "chore: scaffold Terraform for delivery run",
                "files": ["main.tf", "variables.tf", "outputs.tf"],
                "silent_apply": False,
                "message": "Terraform generated as PR/bundle — never silent apply.",
            }
        if to_stage == "plan" and "action_diff" not in artifacts:
            artifacts["action_diff"] = {
                "plan_summary": "Terraform plan: +12 ~3 -0",
                "blast_radius": "medium",
                "rollback": "terraform destroy targeted resources / revert PR",
                "expected_result": "Infra matches desired state without deleting prod data",
                "preflight": "terraform plan -out=tfplan",
            }
        if to_stage == "apply" and "apply_result" not in artifacts:
            artifacts["apply_result"] = {
                "status": "proposed",
                "gated": True,
                "message": "Apply proposed under env×role gate; not auto-executed.",
            }
        if to_stage == "code" and "code_pr" not in artifacts:
            artifacts["code_pr"] = {
                "status": "proposed",
                "title": "feat: scaffold application service",
                "files": ["README.md", "src/main.py", ".github/workflows/ci.yml"],
            }
        if to_stage == "done":
            row.status = "completed"

        row.stage = to_stage
        row.artifacts = artifacts
        if approved_by:
            row.approved_by = approved_by[:120]
        row.updated_at = _now()
        session.commit()
        session.refresh(row)
        return _dict(row)


def _enqueue_architecture_job(run_id: str) -> None:
    try:
        from app.intelligence.queue import enqueue_architecture

        enqueue_architecture(run_id)
    except Exception:
        from app.agents.solution_architect.jobs import generate_architecture

        generate_architecture(run_id)


def ingest_docs(run_id: str, *, docs: str, user_role: str) -> dict[str, Any]:
    _require_stage_role(user_role, "ingest")
    with SessionLocal() as session:
        row = session.get(DeliveryRun, run_id)
        if row is None:
            raise LookupError("Delivery run not found")
        artifacts = dict(row.artifacts or {})
        artifacts["docs"] = (docs or "")[:100_000]
        artifacts["requirements"] = artifacts["docs"]
        row.artifacts = artifacts
        row.updated_at = _now()
        project_id = row.project_id
        run_id = row.id
        session.commit()
        session.refresh(row)
        payload = _dict(row)
    try:
        from app.platform.engineering.artifacts import save_artifact
        from app.platform.engineering.generate import _save_requirement
        from app.platform.engineering.knowledge import remember

        save_artifact(
            project_id=project_id,
            name="requirements.md",
            filename="requirements.md",
            kind="document",
            origin="upload",
            content_text=docs or "",
            delivery_run_id=run_id,
            created_by="",
            validate=False,
        )
        _save_requirement(
            project_id=project_id,
            category="functional",
            title="Ingested requirements",
            statement=(docs or "")[:8000],
            source="document",
            delivery_run_id=run_id,
        )
        remember(
            project_id=project_id,
            summary="Requirements ingested for delivery run",
            kind="requirement",
            category="requirement",
            source="document",
            confidence="high",
            status="active",
            extra={"delivery_run_id": run_id},
        )
    except Exception:
        pass
    return payload
