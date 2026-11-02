"""Bounded auto-fix / retry loop for failed provider and Terraform actions."""
from __future__ import annotations

import json
import time
from typing import Any, Optional

from app.core import azure_client
from app.chat import chat_memory
from app.execution import service

MAX_RETRIES = 3
BASE_BACKOFF_SECONDS = 2

_DEBUG_SYSTEM = """
You diagnose a failed infrastructure or deployment action and propose ONE minimal
fix. Return ONLY JSON:
{
  "root_cause": "",
  "fix_summary": "",
  "retry_safe": true,
  "modified_args": [],
  "rollback_needed": false,
  "notes": ""
}
Rules: never invent credentials; preserve provider/executable; modified_args must
be a full replacement argv without the executable; if unsafe, set retry_safe=false.
""".strip()


def _failure_context(action: dict[str, Any]) -> str:
    result = action.get("result") or {}
    return json.dumps(
        {
            "action_id": action.get("id"),
            "provider": action.get("provider"),
            "status": action.get("status"),
            "error": action.get("error"),
            "command_preview": action.get("command_preview"),
            "target": action.get("target"),
            "result": {
                "stdout": str(result.get("stdout") or "")[:4000],
                "stderr": str(result.get("stderr") or "")[:4000],
                "steps": result.get("steps"),
            },
            "risk": action.get("risk"),
            "rollback": action.get("rollback"),
        },
        ensure_ascii=True,
    )


def propose_fix(action_id: str, *, project_context: str = "") -> dict[str, Any]:
    """Ask the model for a bounded fix proposal for a failed action."""
    action = service.get_action(action_id)
    if action.get("status") not in {"failed", "verification_failed"}:
        raise ValueError("Only failed actions can enter the debug loop")
    prompt = (
        "Failed action evidence:\n"
        + _failure_context(action)
        + ("\n\nProject context:\n" + project_context[:8000] if project_context else "")
    )
    completion = azure_client.chat(
        [
            {"role": "system", "content": _DEBUG_SYSTEM},
            {"role": "user", "content": prompt},
        ],
        temperature=0,
        response_format={"type": "json_object"},
    )
    try:
        parsed = json.loads(completion.choices[0].message.content or "{}")
    except json.JSONDecodeError:
        parsed = {}
    return {
        "action_id": action_id,
        "root_cause": str(parsed.get("root_cause") or "")[:2000],
        "fix_summary": str(parsed.get("fix_summary") or "")[:2000],
        "retry_safe": bool(parsed.get("retry_safe")),
        "modified_args": [str(item) for item in (parsed.get("modified_args") or [])][:128],
        "rollback_needed": bool(parsed.get("rollback_needed")),
        "notes": str(parsed.get("notes") or "")[:2000],
        "original": {
            "provider": action.get("provider"),
            "executable": (action.get("operation") or {}).get("executable"),
            "args": (action.get("operation") or {}).get("args") or [],
            "target": action.get("target"),
            "access_scope": action.get("access_scope"),
        },
    }


def create_retry_action(
    action_id: str,
    proposal: dict[str, Any],
    *,
    access_level: str = "ask_approval",
    requested_by: str = "debug_loop",
) -> dict[str, Any]:
    """Create a new gated action that applies the proposed fix."""
    if not proposal.get("retry_safe"):
        raise ValueError("Proposed fix is marked not retry-safe")
    original = proposal.get("original") or {}
    action = service.get_action(action_id)
    operation = action.get("operation") or {}
    args = proposal.get("modified_args") or original.get("args") or operation.get("args") or []
    if not args:
        raise ValueError("Retry requires modified or original args")
    rollback_operation = operation.get("rollback_operation")
    return service.create_action(
        project_id=action["project_id"],
        provider=str(original.get("provider") or action["provider"]),
        executable=str(original.get("executable") or operation.get("executable")),
        args=[str(item) for item in args],
        target=str(original.get("target") or action.get("target") or ""),
        access_scope=str(original.get("access_scope") or action.get("access_scope") or "write"),
        expected_result=f"Retry succeeds after fix: {proposal.get('fix_summary')}",
        risk=f"Retry of failed action {action_id}. {proposal.get('root_cause')}",
        rollback=str(operation.get("rollback") or "Use prior rollback_operation"),
        preflight=list(operation.get("preflight") or []),
        preflight_expect=str(operation.get("preflight_expect") or ""),
        verify=list(operation.get("verify") or []),
        requested_by=requested_by,
        access_level=access_level,
        why=str(proposal.get("fix_summary") or "Debug-loop retry"),
        blast_radius=str(action.get("blast_radius") or "medium"),
        degrade_plan=str(action.get("degrade_plan") or ""),
        rollback_operation=rollback_operation if isinstance(rollback_operation, dict) else None,
        cloud_provider=str(operation.get("cloud_provider") or ""),
    )


def run_debug_cycle(
    action_id: str,
    *,
    chat_id: Optional[str] = None,
    project_context: str = "",
    access_level: str = "ask_approval",
    max_retries: int = MAX_RETRIES,
) -> dict[str, Any]:
    """Propose a fix and create at most one retry action (approval still required)."""
    proposal = propose_fix(action_id, project_context=project_context)
    if not proposal.get("retry_safe"):
        return {
            "ok": False,
            "action_id": action_id,
            "proposal": proposal,
            "retry_action": None,
            "message": "Fix proposed but not marked retry-safe; manual intervention required.",
        }
    # Bound retries by counting prior debug retries referenced in engineering memory / chat.
    attempt = 1
    if chat_id:
        memory = chat_memory.get_memory(chat_id) or {}
        outcomes = memory.get("deployment_outcomes") or []
        attempt = 1 + sum(1 for item in outcomes if "debug_retry" in str(item))
        if attempt > max_retries:
            return {
                "ok": False,
                "action_id": action_id,
                "proposal": proposal,
                "retry_action": None,
                "message": f"Max debug retries ({max_retries}) reached.",
            }
    # Small backoff marker for observability; approval still gates execution.
    time.sleep(min(BASE_BACKOFF_SECONDS * attempt, 8))
    retry = create_retry_action(
        action_id, proposal, access_level=access_level, requested_by="debug_loop"
    )
    if chat_id:
        chat_memory.record_deployment_outcome(
            chat_id,
            action_id=retry["id"],
            status="debug_retry_proposed",
            summary=str(proposal.get("fix_summary") or "")[:200],
        )
    return {
        "ok": True,
        "action_id": action_id,
        "proposal": proposal,
        "retry_action": retry,
        "attempt": attempt,
        "message": "Retry action prepared and awaiting approval.",
    }
