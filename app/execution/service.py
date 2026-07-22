"""Action persistence, approval transitions, and executor control-plane calls."""
from datetime import datetime, timezone
from typing import Any, Optional
from uuid import uuid4

from sqlalchemy import select

from app import connections
from app.db import (
    ExecutionApproval,
    ExecutionEvent,
    ExecutionJob,
    Project,
    SessionLocal,
)
from app.execution.queue import enqueue_action, queue_snapshot
from app.execution.validation import (
    command_preview,
    delete_verification_confirms_absence,
    operation_hash,
    validate_operation,
)

TERMINAL = {"succeeded", "failed", "verification_failed", "rolled_back", "canceled"}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _event(session: Any, action_id: str, event_type: str, payload: dict[str, Any] | None = None) -> None:
    session.add(
        ExecutionEvent(
            id=str(uuid4()), action_id=action_id, event_type=event_type, payload=payload or {}
        )
    )


def compound_result_complete(operation: dict[str, Any], result: dict[str, Any]) -> bool:
    """Ensure an executor reported every persisted compound step."""
    steps = operation.get("steps") if isinstance(operation.get("steps"), list) else []
    expected = len([step for step in steps if isinstance(step, dict)])
    if expected <= 1:
        return True
    completed = result.get("steps") if isinstance(result, dict) else None
    return isinstance(completed, list) and len(completed) >= expected


def _public(job: ExecutionJob, approval: Optional[ExecutionApproval] = None) -> dict[str, Any]:
    return {
        "id": job.id,
        "project_id": job.project_id,
        "provider": job.provider,
        "operation": job.operation,
        "target": job.target,
        "access_scope": job.access_scope,
        "access_level": (job.operation or {}).get("access_level", "ask_approval"),
        "status": job.status,
        "requested_by": job.requested_by,
        "command_preview": job.command_preview,
        "operation_hash": job.operation_hash,
        "expected_result": (job.operation or {}).get("expected_result", ""),
        "risk": (job.operation or {}).get("risk", ""),
        "rollback": (job.operation or {}).get("rollback", ""),
        "result": job.result or {},
        "error": job.error,
        "created_at": job.created_at.isoformat() if job.created_at else None,
        "queued_at": job.queued_at.isoformat() if job.queued_at else None,
        "started_at": job.started_at.isoformat() if job.started_at else None,
        "finished_at": job.finished_at.isoformat() if job.finished_at else None,
        "approval": {
            "id": approval.id,
            "decision": approval.decision,
            "approver": approval.approver,
            "approved_operation_hash": approval.approved_operation_hash,
            "confirmation_count": approval.confirmation_count,
            "decided_at": approval.decided_at.isoformat() if approval.decided_at else None,
        } if approval else None,
    }


def _load(session: Any, action_id: str) -> tuple[ExecutionJob, Optional[ExecutionApproval]]:
    job = session.get(ExecutionJob, action_id)
    if job is None:
        raise KeyError("Action not found")
    approval = session.scalar(
        select(ExecutionApproval).where(ExecutionApproval.action_id == action_id).order_by(ExecutionApproval.created_at.desc())
    )
    return job, approval


def create_action(
    *, project_id: str, provider: str, executable: str, args: list[str], target: str,
    access_scope: str, expected_result: str, risk: str, rollback: str,
    preflight: list[str], preflight_expect: str = "", verify: list[str] | None = None,
    requested_by: str = "user", access_level: str = "ask_approval",
    steps: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    if access_level not in {"ask_approval", "auto_approve", "full_access"}:
        raise ValueError("Unsupported access level")
    if connections.get_secret_fields(project_id, provider) is None:
        raise ValueError(f"No {provider} connection is configured for this project")
    if provider == "github" and "/" in target:
        with SessionLocal() as session:
            project = session.get(Project, project_id)
            mapped = {str(repo).lower() for repo in (project.repos if project else [])}
        if target.lower() not in mapped:
            raise ValueError("GitHub action target is outside the repositories mapped to this project")
    operation = validate_operation(provider, executable, args, target, access_scope, preflight, verify)
    normalized_steps: list[dict[str, Any]] = []
    for step in (steps or []):
        step_provider = str(step.get("provider") or provider)
        step_executable = str(step.get("executable") or "")
        step_scope = str(step.get("access_scope") or access_scope)
        if step_provider != provider or step_scope != access_scope:
            raise ValueError("Compound actions must use one provider and one access scope")
        step_operation = validate_operation(
            step_provider,
            step_executable,
            [str(item) for item in step.get("args", [])],
            str(step.get("target") or ""),
            step_scope,
            [str(item) for item in step.get("preflight", [])],
            [str(item) for item in step.get("verify", [])],
        )
        step_operation.update({
            "expected_result": str(step.get("expected_result") or "")[:1000],
            "risk": str(step.get("risk") or "")[:1000],
            "rollback": str(step.get("rollback") or "")[:1000],
            "skip_if_exists": bool(step.get("skip_if_exists")),
        })
        if step.get("preflight_expect"):
            step_operation["preflight_expect"] = str(step["preflight_expect"])[:100]
        normalized_steps.append(step_operation)
    if normalized_steps:
        operation["steps"] = normalized_steps
    operation.update({
        "expected_result": expected_result[:1000],
        "risk": risk[:1000],
        "rollback": rollback[:1000],
        "access_level": access_level,
        "requires_double_confirmation": access_scope == "write" and access_level == "full_access",
    })
    if preflight_expect:
        operation["preflight_expect"] = preflight_expect[:100]
    action_id = str(uuid4())
    status = "awaiting_approval" if access_scope == "write" else "queued"
    job = ExecutionJob(
        id=action_id,
        project_id=project_id,
        provider=provider,
        operation=operation,
        target=target,
        access_scope=access_scope,
        status=status,
        requested_by=requested_by[:120],
        command_preview=(
            "\n".join(f"{index}. {command_preview(step)}" for index, step in enumerate(normalized_steps, 1))
            if normalized_steps
            else command_preview(operation)
        ),
        operation_hash=operation_hash(operation, access_scope),
    )
    with SessionLocal() as session:
        session.add(job)
        _event(session, action_id, "action_planned", {"provider": provider, "target": target})
        if access_scope == "write":
            approval = ExecutionApproval(
                id=str(uuid4()), action_id=action_id, approved_operation_hash=job.operation_hash
            )
            session.add(approval)
            _event(
                session,
                action_id,
                "approval_required",
                {
                    "operation_hash": job.operation_hash,
                    "mode": "double_confirmation" if access_level == "full_access" else "single_confirmation",
                },
            )
        else:
            job.queued_at = _now()
            _event(session, action_id, "action_queued", {"queue": f"provider.{provider}.read"})
        session.commit()
        response = _public(job, approval if access_scope == "write" else None)
    if access_scope == "read_only":
        try:
            dispatch = enqueue_action(action_id, provider, access_scope)
            _record_dispatch_diagnostic(action_id, dispatch)
        except Exception as exc:  # noqa: BLE001
            mark_result(action_id, "failed", {}, f"Unable to queue action: {exc}")
            raise
    return response


def get_action(action_id: str) -> dict[str, Any]:
    with SessionLocal() as session:
        job, approval = _load(session, action_id)
        verification = (job.result or {}).get("verification")
        if (
            job.status == "verification_failed"
            and isinstance(verification, dict)
            and delete_verification_confirms_absence(
                job.operation,
                int(verification.get("returncode") or 0),
                str(verification.get("stdout") or ""),
                str(verification.get("stderr") or ""),
                bool(verification.get("timed_out")),
            )
        ):
            job.status = "succeeded"
            job.error = ""
            job.finished_at = job.finished_at or _now()
            _event(
                session,
                action_id,
                "action_reconciled",
                {"reason": "delete verification confirmed the target is absent"},
            )
            session.commit()
        return _public(job, approval)


def list_events(action_id: str) -> list[dict[str, Any]]:
    with SessionLocal() as session:
        if session.get(ExecutionJob, action_id) is None:
            raise KeyError("Action not found")
        rows = session.scalars(
            select(ExecutionEvent).where(ExecutionEvent.action_id == action_id).order_by(ExecutionEvent.created_at.asc())
        ).all()
        return [{"id": row.id, "type": row.event_type, "payload": row.payload or {}, "created_at": row.created_at.isoformat()} for row in rows]


def _record_dispatch_diagnostic(action_id: str, details: dict[str, Any]) -> None:
    with SessionLocal() as session:
        if session.get(ExecutionJob, action_id) is None:
            return
        _event(session, action_id, "action_queue_diagnostic", details)
        session.commit()


def diagnose_action(action_id: str) -> dict[str, Any]:
    """Diagnose queue starvation and append a rate-limited event for UI/LLM."""
    with SessionLocal() as session:
        job, _approval = _load(session, action_id)
        snapshot = queue_snapshot(job.provider, job.access_scope, action_id)
        age_seconds = 0
        if job.queued_at:
            queued_at = job.queued_at
            if queued_at.tzinfo is None:
                queued_at = queued_at.replace(tzinfo=timezone.utc)
            age_seconds = max(0, int((_now() - queued_at).total_seconds()))
        if job.status == "queued" and not snapshot.get("executor_available"):
            message = f"No {job.provider} executor worker is listening to {snapshot['queue']}; the provider CLI has not started."
            recommendation = "Start the provider executor or stop this action. Do not retry the CLI command until an executor is available."
        elif job.status == "queued":
            message = f"The action is waiting in {snapshot['queue']} for an available executor."
            recommendation = "Keep waiting while the executor claims the job, or stop it to prevent execution."
        elif job.status == "running":
            message = f"The {job.provider} executor has claimed the action and is running the CLI."
            recommendation = "Inspect the live CLI output; stop the action if the command is no longer desired."
        else:
            message = f"Action status is {job.status}."
            recommendation = "No queue intervention is required."
        payload = {
            **snapshot,
            "status": job.status,
            "age_seconds": age_seconds,
            "message": message,
            "recommendation": recommendation,
        }
        recent = session.scalar(
            select(ExecutionEvent)
            .where(ExecutionEvent.action_id == action_id, ExecutionEvent.event_type == "action_queue_diagnostic")
            .order_by(ExecutionEvent.created_at.desc())
        )
        recent_at = recent.created_at if recent else None
        if recent_at is None:
            should_record = True
        else:
            if recent_at.tzinfo is None:
                recent_at = recent_at.replace(tzinfo=timezone.utc)
            should_record = (_now() - recent_at).total_seconds() >= 15
        if should_record:
            _event(session, action_id, "action_queue_diagnostic", payload)
            session.commit()
        return payload


def approve_action(action_id: str, approver: str) -> dict[str, Any]:
    with SessionLocal() as session:
        job, approval = _load(session, action_id)
        if job.access_scope != "write" or job.status != "awaiting_approval" or approval is None:
            raise ValueError("Action is not awaiting approval")
        current_hash = operation_hash(job.operation, job.access_scope)
        if current_hash != approval.approved_operation_hash or current_hash != job.operation_hash:
            raise ValueError("The operation changed after it was previewed")
        if (job.operation or {}).get("access_level") == "full_access" and approval.confirmation_count < 1:
            approval.confirmation_count = 1
            approval.decision = "first_confirmed"
            approval.approver = approver[:120]
            approval.decided_at = _now()
            _event(
                session,
                action_id,
                "action_confirmation_required",
                {"confirmation_count": 1, "required": 2},
            )
            session.commit()
            return _public(job, approval)
        if (job.operation or {}).get("access_level") == "full_access":
            approval.confirmation_count = 2
        approval.decision = "approved"
        approval.approver = approver[:120]
        approval.decided_at = _now()
        job.status = "queued"
        job.queued_at = _now()
        _event(session, action_id, "action_queued", {"queue": f"provider.{job.provider}.write"})
        session.commit()
        result = _public(job, approval)
    try:
        dispatch = enqueue_action(action_id, job.provider, job.access_scope)
        _record_dispatch_diagnostic(action_id, dispatch)
    except Exception as exc:  # noqa: BLE001
        mark_result(action_id, "failed", {}, f"Unable to queue action: {exc}")
        raise
    return result


def reject_action(action_id: str, approver: str, reason: str) -> dict[str, Any]:
    with SessionLocal() as session:
        job, approval = _load(session, action_id)
        if job.status != "awaiting_approval" or approval is None:
            raise ValueError("Action is not awaiting approval")
        approval.decision = "rejected"
        approval.approver = approver[:120]
        approval.decided_at = _now()
        job.status = "failed"
        job.error = reason[:1000] or "Action rejected"
        job.finished_at = _now()
        _event(session, action_id, "action_rejected", {"reason": job.error})
        session.commit()
        return _public(job, approval)


def cancel_action(action_id: str, requested_by: str = "user") -> dict[str, Any]:
    """Cancel a queued or running action without allowing a late result to win."""
    with SessionLocal() as session:
        job, approval = _load(session, action_id)
        if job.status not in {"queued", "running"}:
            raise ValueError("Only queued or running actions can be canceled")
        job.status = "canceled"
        job.error = f"Canceled by {requested_by[:120]}"
        job.finished_at = _now()
        _event(session, action_id, "action_canceled", {"requested_by": requested_by[:120]})
        session.commit()
        return _public(job, approval)


def claim_for_executor(action_id: str, provider: str) -> dict[str, Any]:
    with SessionLocal() as session:
        job, approval = _load(session, action_id)
        if job.provider != provider:
            raise ValueError("Action is assigned to a different provider executor")
        if job.status != "queued":
            raise ValueError("Action is not queued")
        if job.access_scope == "write" and (approval is None or approval.decision != "approved"):
            raise ValueError("Write action has not been approved")
        job.status = "running"
        job.started_at = _now()
        _event(session, action_id, "action_started", {"provider": provider})
        session.commit()
        fields = connections.get_secret_fields(job.project_id, provider) or {}
        return {"id": job.id, "project_id": job.project_id, "provider": job.provider, "operation": job.operation, "access_scope": job.access_scope, "credentials": fields}


def is_canceled(action_id: str, provider: str) -> bool:
    with SessionLocal() as session:
        job = session.get(ExecutionJob, action_id)
        if job is None:
            raise KeyError("Action not found")
        if job.provider != provider:
            raise ValueError("Executor provider does not match action provider")
        return job.status == "canceled"


def append_event(action_id: str, event_type: str, payload: dict[str, Any]) -> None:
    with SessionLocal() as session:
        if session.get(ExecutionJob, action_id) is None:
            raise KeyError("Action not found")
        _event(session, action_id, event_type, payload)
        session.commit()


def validate_executor_provider(action_id: str, provider: str) -> None:
    with SessionLocal() as session:
        job = session.get(ExecutionJob, action_id)
        if job is None:
            raise KeyError("Action not found")
        if job.provider != provider:
            raise ValueError("Executor provider does not match action provider")


def mark_result(action_id: str, status: str, result: dict[str, Any], error: str = "") -> None:
    if status not in TERMINAL:
        raise ValueError("Invalid terminal action status")
    with SessionLocal() as session:
        job, _approval = _load(session, action_id)
        if job.status == "canceled":
            return
        if status == "succeeded" and not compound_result_complete(job.operation or {}, result):
            expected = len([step for step in (job.operation or {}).get("steps", []) if isinstance(step, dict)])
            received = len(result.get("steps", [])) if isinstance(result, dict) and isinstance(result.get("steps"), list) else 0
            status = "failed"
            error = (
                f"Executor returned an incomplete compound result: expected {expected} steps, "
                f"received {received}. Rebuild and redeploy the provider executor image."
            )
            result = {
                **(result if isinstance(result, dict) else {}),
                "compound_execution": {"expected_steps": expected, "completed_steps": received},
            }
        job.status = status
        job.result = result
        job.error = error[:2000]
        job.finished_at = _now()
        _event(session, action_id, f"action_{'succeeded' if status == 'succeeded' else 'failed'}", {"status": status, "error": job.error})
        session.commit()
