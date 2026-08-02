"""End-to-end deployment orchestration: validate → plan → apply → verify → health."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Optional
from uuid import uuid4

from app.execution import debug_loop, service, terraform_runner


@dataclass
class DeployStage:
    name: str
    status: str = "pending"
    detail: str = ""
    action_id: str = ""


@dataclass
class DeployPlan:
    id: str
    project_id: str
    strategy: str
    environment: str
    stages: list[DeployStage] = field(default_factory=list)
    canary_percent: int = 0
    rollback_on_health_fail: bool = True
    ok: bool = True
    message: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _stage(name: str, **kwargs: Any) -> DeployStage:
    return DeployStage(name=name, **kwargs)


def build_deploy_plan(
    project_id: str,
    *,
    strategy: str = "all_at_once",
    environment: str = "dev",
    canary_percent: int = 10,
    workspace_name: str = "default",
) -> DeployPlan:
    """Create an ordered deployment plan (does not execute writes yet)."""
    strategy = strategy if strategy in {"all_at_once", "canary", "blue_green"} else "all_at_once"
    stages = [
        _stage("lint_validate", detail="Terraform validate / pipeline lint"),
        _stage("plan", detail="Produce Terraform or release plan diff"),
        _stage("approval", detail="Human approval with rollback plan"),
        _stage("apply", detail="Apply approved change"),
    ]
    if strategy == "canary":
        stages.append(
            _stage(
                "canary",
                detail=f"Route {max(1, min(canary_percent, 50))}% traffic and verify health",
            )
        )
        stages.append(_stage("full_rollout", detail="Promote to 100% after canary success"))
    elif strategy == "blue_green":
        stages.append(_stage("switch", detail="Switch traffic to the green slot after health checks"))
    stages.append(_stage("verify", detail="Postcondition verification"))
    stages.append(_stage("health_check", detail="SLO / endpoint / revision health checks"))
    if True:
        stages.append(
            _stage(
                "rollback_ready",
                detail="Machine-executable rollback armed if health checks fail",
            )
        )
    return DeployPlan(
        id=str(uuid4()),
        project_id=project_id,
        strategy=strategy,
        environment=environment,
        stages=stages,
        canary_percent=canary_percent if strategy == "canary" else 0,
        message=f"Deployment plan ready for workspace={workspace_name}",
    )


def run_deploy_pipeline(
    project_id: str,
    *,
    workspace_name: str = "default",
    strategy: str = "all_at_once",
    environment: str = "dev",
    access_level: str = "ask_approval",
    requested_by: str = "deploy_orchestrator",
    canary_percent: int = 10,
) -> dict[str, Any]:
    """Execute read-only validate/plan locally when possible, then gate apply."""
    plan = build_deploy_plan(
        project_id,
        strategy=strategy,
        environment=environment,
        canary_percent=canary_percent,
        workspace_name=workspace_name,
    )
    pipeline = terraform_runner.pipeline(
        project_id,
        workspace_name=workspace_name,
        access_level=access_level,
        requested_by=requested_by,
        run_local_plan=True,
    )
    for stage in plan.stages:
        if stage.name == "lint_validate":
            stage.status = "succeeded" if pipeline.get("ok") or pipeline.get("phases") else "pending"
            stage.detail = "init/validate completed" if pipeline.get("ok") else str(pipeline.get("error") or stage.detail)
        elif stage.name == "plan":
            summary = pipeline.get("plan_summary") or {}
            stage.status = "succeeded" if summary or pipeline.get("ok") else "pending"
            stage.detail = json_safe_summary(summary) or stage.detail
        elif stage.name == "approval":
            action = pipeline.get("action") or {}
            stage.status = action.get("status") or "pending"
            stage.action_id = action.get("id") or ""
            stage.detail = action.get("command_preview") or stage.detail
        elif stage.name == "apply":
            action = pipeline.get("action") or {}
            stage.status = "awaiting_approval" if action else "pending"
            stage.action_id = action.get("id") or ""
        elif stage.name in {"canary", "full_rollout", "switch"}:
            stage.status = "planned"
            stage.detail = (
                f"{strategy} stage armed; execute after apply succeeds "
                f"(canary={plan.canary_percent}%)."
            )
        elif stage.name in {"verify", "health_check", "rollback_ready"}:
            stage.status = "planned"
    plan.ok = bool(pipeline.get("ok"))
    plan.message = pipeline.get("error") or "Apply action prepared; approve to continue."
    return {
        "plan": plan.to_dict(),
        "pipeline": {
            "ok": pipeline.get("ok"),
            "phases": pipeline.get("phases"),
            "plan_summary": pipeline.get("plan_summary"),
            "action": pipeline.get("action"),
            "error": pipeline.get("error"),
        },
    }


def json_safe_summary(summary: dict[str, Any]) -> str:
    if not summary:
        return ""
    return (
        f"Plan: {summary.get('add')} add, {summary.get('change')} change, "
        f"{summary.get('destroy')} destroy"
    )


def handle_failed_deploy(
    action_id: str,
    *,
    chat_id: Optional[str] = None,
    project_context: str = "",
    access_level: str = "ask_approval",
) -> dict[str, Any]:
    """On health/apply failure, enter the debug loop and keep rollback available."""
    action = service.get_action(action_id)
    rollback = action.get("rollback_operation") or action.get("rollback")
    debug = debug_loop.run_debug_cycle(
        action_id,
        chat_id=chat_id,
        project_context=project_context,
        access_level=access_level,
    )
    return {
        "action": action,
        "rollback": rollback,
        "debug": debug,
        "auto_rollback_recommended": action.get("status")
        in {"failed", "verification_failed"},
    }
