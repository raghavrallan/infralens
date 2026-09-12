"""Inbound integration APIs for n8n (and compatible automation).

Auth: JWT (same as UI) OR ``Authorization: Bearer <INTEGRATIONS_API_KEY>``
for paths under ``/api/integrations``. Risk Engine / RBAC still apply via
existing service functions — n8n cannot bypass gates.
"""
from __future__ import annotations

import os
from typing import Any, Literal, Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel, Field

from app.agents.runtime.flags import get_feature_flags
from app.core import auth
from app.core.rbac import GATE_MIN_ROLE, assert_capability, has_min_role
from app.integrations import webhooks
from app.intelligence import workflows as intel
from app.intelligence.queue import enqueue_run

router = APIRouter(prefix="/api/integrations", tags=["integrations"])


class DecideBody(BaseModel):
    decision: Literal["approved", "rejected"]
    decided_by: str = Field(default="n8n", max_length=120)


class RunWorkflowBody(BaseModel):
    trigger: str = "n8n"


def _integrations_api_key() -> str:
    return (os.environ.get("INTEGRATIONS_API_KEY") or "").strip()


def require_integration_actor(
    request: Request,
    authorization: Optional[str] = Header(default=None),
) -> dict[str, Any]:
    """Accept UI JWT or shared integrations API key."""
    existing = getattr(request.state, "user", None)
    if isinstance(existing, dict) and existing.get("id"):
        return existing

    token = auth.bearer_token(authorization)
    api_key = _integrations_api_key()
    if api_key and token and token == api_key:
        return {
            "id": "integration:n8n",
            "username": "n8n",
            "display_name": "n8n integration",
            "role": os.environ.get("INTEGRATIONS_API_ROLE", "devops_lead"),
        }

    user = auth.verify_token(token)
    if user is None:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return user


@router.get("/status")
def integrations_status(
    _user: dict[str, Any] = Depends(require_integration_actor),
) -> dict[str, Any]:
    flags = get_feature_flags()
    return {
        "feature_flags": flags,
        "n8n_webhooks_enabled": webhooks.integrations_enabled(),
        "webhook_url_configured": bool(webhooks.webhook_url()),
        "hmac_configured": bool(webhooks.webhook_secret()),
        "integrations_api_key_configured": bool(_integrations_api_key()),
    }


@router.post("/webhooks/test")
def test_webhook(
    _user: dict[str, Any] = Depends(require_integration_actor),
) -> dict[str, Any]:
    from app.integrations import n8n_schemas

    payload = n8n_schemas.envelope(
        "workflow.run_completed",
        project_id="test",
        data={
            "run_id": "test",
            "workflow_id": "test",
            "status": "test",
            "finding_count": 0,
        },
    )
    ok = webhooks.emit_event(payload)
    return {"ok": ok, "payload": payload}


@router.post("/approvals/{approval_id}/decide")
def integration_decide_approval(
    approval_id: str,
    body: DecideBody,
    user: dict[str, Any] = Depends(require_integration_actor),
) -> dict[str, Any]:
    from app.core.db import Approval, Finding, SessionLocal

    with SessionLocal() as session:
        approval = session.get(Approval, approval_id)
        if approval is None:
            raise HTTPException(status_code=404, detail="Approval not found")
        finding = session.get(Finding, approval.finding_id)
        gate = approval.gate or "human_approval"
        min_role = GATE_MIN_ROLE.get(gate, "devops_lead")
        title = finding.title if finding else ""

    if not has_min_role(str(user.get("role") or "viewer"), min_role):
        raise HTTPException(
            status_code=403,
            detail=f"Approval requires {min_role}+ (integration actor role too low)",
        )
    decided = intel.decide_approval(
        approval_id,
        body.decision,
        decided_by=body.decided_by or user.get("username") or "n8n",
    )
    if decided is None:
        raise HTTPException(status_code=404, detail="Approval not found or invalid decision")
    decided.setdefault("title", title)
    return decided


@router.post("/workflows/{workflow_id}/run")
def integration_run_workflow(
    workflow_id: str,
    body: RunWorkflowBody | None = None,
    user: dict[str, Any] = Depends(require_integration_actor),
) -> dict[str, Any]:
    body = body or RunWorkflowBody()
    assert_capability(user, "run_workflow")
    workflow = intel.get_workflow(workflow_id)
    if workflow is None:
        raise HTTPException(status_code=404, detail="Workflow not found")
    run = intel.create_run(workflow_id, trigger=body.trigger or "n8n")
    if run is None:
        raise HTTPException(status_code=404, detail="Workflow not found")
    try:
        enqueue_run(run["id"])
    except Exception as exc:  # noqa: BLE001
        intel.mark_run_failed(run["id"], f"Could not enqueue run: {exc}")
        raise HTTPException(
            status_code=503,
            detail=f"Could not reach the job queue ({exc})",
        ) from exc
    return run
