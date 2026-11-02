"""Heuristic + LangChain AI recommendations over the unified projection."""
from __future__ import annotations

import json
import os
import re
from typing import Any


def heuristic_recommendations(
    items: list[dict[str, Any]],
    artifacts: list[dict[str, Any]],
    risks: list[dict[str, Any]],
    memory_rows: list[dict[str, Any]],
    *,
    delivery: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    recs: list[dict[str, Any]] = []
    for risk in risks:
        recs.append(
            {
                "id": f"risk-{risk['id']}",
                "title": risk.get("recommendation") or risk["title"],
                "reason": risk.get("impact") or risk["title"],
                "impact": risk.get("severity") or "medium",
                "priority": risk.get("severity") or "medium",
                "related_task_id": risk.get("related_task_id") or "",
                "action": "add_task",
            }
        )
    ready = next(
        (item for item in items if item["status"] in {"ready", "in_progress", "validation_required"}),
        None,
    )
    if ready:
        recs.append(
            {
                "id": f"next-{ready['id']}",
                "title": f"Work next: {ready['title']}",
                "reason": ready.get("ai_recommendation") or "Highest-priority incomplete delivery task.",
                "impact": "medium",
                "priority": ready.get("priority") or "medium",
                "related_task_id": ready["id"],
                "action": "open_task",
            }
        )
    if any(row.get("stale") for row in memory_rows):
        recs.append(
            {
                "id": "stale-memory",
                "title": "Verify stale engineering memory",
                "reason": "Some memories are older than 90 days or superseded.",
                "impact": "medium",
                "priority": "medium",
                "related_task_id": "",
                "action": "open_memory",
            }
        )
    kinds = {item.get("kind") for item in artifacts}
    if "terraform" not in kinds and any(item.get("stage") == "infrastructure" for item in items):
        recs.append(
            {
                "id": "gen-tf",
                "title": "Generate Terraform for open infra tasks",
                "reason": "Infrastructure tasks exist but no Terraform artifact is attached.",
                "impact": "high",
                "priority": "high",
                "related_task_id": next((i["id"] for i in items if i.get("stage") == "infrastructure"), ""),
                "action": "generate_terraform",
            }
        )
    repair = dict((delivery or {}).get("terraform_repair") or {})
    if str(repair.get("status") or "") in {"failed", "exhausted"}:
        recs.append(
            {
                "id": "retry-repair",
                "title": "Retry Terraform repair loop",
                "reason": str(repair.get("last_error") or "Prior Terraform repair did not converge."),
                "impact": "high",
                "priority": "high",
                "related_task_id": "",
                "action": "retry_repair",
            }
        )
    stage = str((delivery or {}).get("stage") or "")
    if stage == "terraform" and "terraform" not in kinds:
        recs.append(
            {
                "id": "delivery-gen-modules",
                "title": "Generate module/env Terraform from architecture",
                "reason": "Delivery is on the terraform stage without module/env artifacts yet.",
                "impact": "high",
                "priority": "high",
                "related_task_id": "",
                "action": "generate_terraform",
            }
        )
    return recs[:8]


def _ai_enabled() -> bool:
    flag = (os.environ.get("ENGINEERING_AI_RECS") or "true").strip().lower()
    return flag not in {"0", "false", "no", "off"}


def ai_recommendations(projection: dict[str, Any], risks: list[dict[str, Any]]) -> list[dict[str, Any]] | None:
    if not _ai_enabled():
        return None
    try:
        from app.agents.runtime.llm import get_chat_llm
    except Exception:
        return None
    delivery = projection.get("delivery") or {}
    tasks = projection.get("tasks") or []
    summary = {
        "delivery_stage": delivery.get("stage"),
        "architecture_status": delivery.get("architecture_status"),
        "repair": delivery.get("terraform_repair"),
        "task_counts": projection.get("task_counts"),
        "open_tasks": [
            {
                "id": t.get("id"),
                "title": t.get("title"),
                "stage": t.get("stage"),
                "status": t.get("status"),
                "missing_artifacts": t.get("missing_artifacts"),
            }
            for t in tasks
            if t.get("status") != "completed"
        ][:12],
        "risks": [
            {"title": r.get("title"), "severity": r.get("severity"), "recommendation": r.get("recommendation")}
            for r in risks[:6]
        ],
        "artifact_count": len(projection.get("artifacts") or []),
    }
    prompt = (
        "You are InfraLens engineering command. Return JSON only: "
        '{"recommendations":[{"id":"string","title":"string","reason":"string",'
        '"impact":"low|medium|high|critical","priority":"low|medium|high|critical",'
        '"related_task_id":"","action":"add_task|open_task|generate_terraform|retry_repair|open_memory"}]}. '
        "Max 5 recommendations. Prefer concrete next actions for delivery/IaC. "
        f"Project state:\n{json.dumps(summary)[:6000]}"
    )
    try:
        llm = get_chat_llm(temperature=0.1)
        raw = llm.invoke(prompt)
        text = getattr(raw, "content", None) or str(raw)
        if isinstance(text, list):
            text = "".join(str(part) for part in text)
        match = re.search(r"\{[\s\S]*\}", str(text))
        if not match:
            return None
        payload = json.loads(match.group(0))
        rows = payload.get("recommendations") if isinstance(payload, dict) else None
        if not isinstance(rows, list):
            return None
        out: list[dict[str, Any]] = []
        allowed = {"add_task", "open_task", "generate_terraform", "retry_repair", "open_memory"}
        for idx, row in enumerate(rows[:5]):
            if not isinstance(row, dict):
                continue
            action = str(row.get("action") or "add_task")
            if action not in allowed:
                action = "add_task"
            out.append(
                {
                    "id": str(row.get("id") or f"ai-{idx}"),
                    "title": str(row.get("title") or "Follow-up")[:200],
                    "reason": str(row.get("reason") or "")[:500],
                    "impact": str(row.get("impact") or "medium"),
                    "priority": str(row.get("priority") or "medium"),
                    "related_task_id": str(row.get("related_task_id") or ""),
                    "action": action,
                    "source": "langchain",
                }
            )
        return out or None
    except Exception:
        return None


def build_recommendations(projection: dict[str, Any], risks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    ai = ai_recommendations(projection, risks)
    if ai:
        return ai
    return heuristic_recommendations(
        projection.get("tasks") or [],
        projection.get("artifacts") or [],
        risks,
        projection.get("memory") or [],
        delivery=projection.get("delivery"),
    )
