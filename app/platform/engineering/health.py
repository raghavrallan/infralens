"""Project health, blockers, recommendations, and production readiness."""
from __future__ import annotations

from typing import Any

from sqlalchemy import select

from app.core.db import Approval, Finding, ProjectRisk, SessionLocal
from app.platform.engineering import recommendations as rec_engine
from app.platform.engineering import sync as eng_sync
from app.platform.engineering import tasks as task_store

STAGE_HEALTH = (
    ("architecture", ("architecture", "requirements")),
    ("infrastructure", ("infrastructure",)),
    ("security", ("security",)),
    ("testing", ("testing",)),
    ("delivery", ("cicd", "deployment", "validation")),
    ("documentation", ("documentation",)),
)


def _pct(done: int, total: int) -> int:
    if total <= 0:
        return 0
    return int(round(100 * done / total))


def build_health(project_id: str) -> dict[str, Any]:
    projection = eng_sync.project_projection(project_id)
    items = projection["tasks"]
    memory_rows = projection["memory"]
    artifact_rows = projection["artifacts"]
    delivery = projection.get("delivery")
    risks = _open_risks(project_id)
    bars: dict[str, dict[str, Any]] = {}
    for name, stages in STAGE_HEALTH:
        subset = [item for item in items if item["stage"] in stages]
        done = sum(1 for item in subset if item["status"] == "completed")
        bars[name] = {
            "label": name.title(),
            "percent": _pct(done, len(subset)) if subset else _pct(0, 1),
            "done": done,
            "total": len(subset),
        }
    verified = sum(1 for row in memory_rows if row["status"] in {"active", "verified"})
    bars["memory"] = {
        "label": "Engineering Memory",
        "percent": _pct(verified, len(memory_rows)) if memory_rows else 0,
        "done": verified,
        "total": len(memory_rows),
    }
    overall = int(round(sum(bar["percent"] for bar in bars.values()) / max(1, len(bars))))
    blockers = _blockers(items, risks, delivery_run_id=projection.get("delivery_run_id") or "")
    recommendations = rec_engine.build_recommendations(projection, risks)
    timeline = _timeline(items, delivery)
    readiness = production_readiness(project_id, items=items, risks=risks)
    architecture_status = str((delivery or {}).get("architecture_status") or "")
    summary = _summary(bars, blockers, items, readiness, architecture_status=architecture_status, delivery=delivery)
    return {
        "overall": overall,
        "bars": bars,
        "blockers": blockers,
        "recommendations": recommendations,
        "timeline": timeline,
        "readiness": readiness,
        "summary": summary,
        "next_actions": [item["title"] for item in recommendations[:3]],
        "task_counts": projection["task_counts"],
        "artifact_count": len(artifact_rows),
        "memory_count": len(memory_rows),
        "pending_adrs": _pending_adrs(project_id),
        "delivery_stage": (delivery or {}).get("stage") or "",
        "delivery_stage_label": (delivery or {}).get("stage_label") or "",
        "delivery_run_id": projection.get("delivery_run_id") or "",
        "terraform_repair": (delivery or {}).get("terraform_repair") or {},
        "synced_at": projection.get("synced_at"),
    }


def production_readiness(
    project_id: str,
    *,
    items: list[dict[str, Any]] | None = None,
    risks: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    items = items if items is not None else task_store.list_tasks(project_id)
    risks = risks if risks is not None else _open_risks(project_id)
    checks = []

    def add(name: str, ok: bool, detail: str = "") -> None:
        checks.append({"name": name, "ok": ok, "detail": detail})

    arch_done = [item for item in items if item["stage"] == "architecture" and item["status"] == "completed"]
    arch_total = [item for item in items if item["stage"] == "architecture"]
    add(
        "Architecture approved",
        bool(arch_done),
        (
            f"{len(arch_done)}/{len(arch_total)} architecture tasks complete"
            if arch_total
            else "No architecture tasks yet"
        ),
    )
    infra = [item for item in items if item["stage"] == "infrastructure"]
    add(
        "Infrastructure validated",
        all(item["status"] == "completed" for item in infra) if infra else False,
        f"{sum(1 for i in infra if i['status']=='completed')}/{len(infra)} infra tasks",
    )
    sec = [item for item in items if item["stage"] == "security"]
    add(
        "Security approved",
        all(item["status"] == "completed" for item in sec) if sec else False,
        f"{sum(1 for i in sec if i['status']=='completed')}/{len(sec)} security tasks",
    )
    tests = [item for item in items if item["stage"] == "testing"]
    add(
        "Tests passed",
        all(item["status"] == "completed" for item in tests) if tests else True,
        f"{sum(1 for i in tests if i['status']=='completed')}/{len(tests)} test tasks" if tests else "No testing tasks in this delivery",
    )
    add("No critical open risks", not any(risk["severity"] in {"critical", "high"} for risk in risks))
    missing_art = [item for item in items if item.get("missing_artifacts")]
    add("Required artifacts available", not missing_art, f"{len(missing_art)} tasks missing files")
    blocked = any(not check["ok"] for check in checks)
    return {
        "ready": not blocked,
        "status": "Ready" if not blocked else "Not Ready — production blocked",
        "checks": checks,
        "percent": _pct(sum(1 for check in checks if check["ok"]), len(checks)),
    }


def _open_risks(project_id: str) -> list[dict[str, Any]]:
    with SessionLocal() as session:
        rows = session.scalars(
            select(ProjectRisk).where(
                ProjectRisk.project_id == project_id,
                ProjectRisk.status == "open",
            )
        ).all()
        return [
            {
                "id": row.id,
                "title": row.title,
                "severity": row.severity,
                "impact": row.impact,
                "recommendation": row.recommendation,
                "href": row.href or "delivery",
                "related_task_id": row.related_task_id,
                "related_decision_id": row.related_decision_id,
            }
            for row in rows
        ]


def _pending_adrs(project_id: str) -> int:
    with SessionLocal() as session:
        rows = session.execute(
            select(Approval.id)
            .join(Finding, Finding.id == Approval.finding_id)
            .where(
                Approval.project_id == project_id,
                Approval.decision == "pending",
                Finding.skill == "solution_architect",
            )
        ).all()
        return len(rows)


def _blockers(
    items: list[dict[str, Any]],
    risks: list[dict[str, Any]],
    *,
    delivery_run_id: str = "",
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for risk in risks:
        severity = risk["severity"]
        task_id = risk.get("related_task_id") or ""
        out.append(
            {
                "id": risk["id"],
                "level": "critical" if severity == "critical" else ("high" if severity == "high" else "medium"),
                "title": risk["title"],
                "href": eng_sync.dashboard_href(task_id=task_id, run_id=delivery_run_id),
                "task_id": task_id,
            }
        )
    for item in items:
        if item["status"] == "blocked":
            out.append(
                {
                    "id": item["id"],
                    "level": "high" if item.get("priority") == "high" else "medium",
                    "title": f"{item['title']} — {item.get('blocked_reason') or 'blocked'}",
                    "href": eng_sync.dashboard_href(task_id=item["id"], run_id=delivery_run_id),
                    "task_id": item["id"],
                }
            )
        if item["status"] == "validation_failed":
            out.append(
                {
                    "id": item["id"] + "-val",
                    "level": "high",
                    "title": f"Validation failed: {item['title']}",
                    "href": eng_sync.dashboard_href(task_id=item["id"], run_id=delivery_run_id),
                    "task_id": item["id"],
                }
            )
        if item.get("missing_artifacts") and item["status"] not in {"not_started", "completed"}:
            out.append(
                {
                    "id": item["id"] + "-art",
                    "level": "medium",
                    "title": f"Missing artifacts on {item['title']}: {', '.join(item['missing_artifacts'][:3])}",
                    "href": eng_sync.dashboard_href(task_id=item["id"], run_id=delivery_run_id),
                    "task_id": item["id"],
                }
            )
    order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
    out.sort(key=lambda row: order.get(row["level"], 9))
    return out[:12]


def _timeline(items: list[dict[str, Any]], delivery: dict[str, Any] | None) -> list[dict[str, Any]]:
    order = ["requirements", "architecture", "infrastructure", "security", "testing", "cicd", "deployment"]
    out = []
    for stage in order:
        subset = [item for item in items if item["stage"] == stage]
        if not subset:
            out.append({"stage": stage, "state": "pending"})
            continue
        if all(item["status"] == "completed" for item in subset):
            state = "done"
        elif any(item["status"] == "blocked" for item in subset):
            state = "blocked"
        elif any(
            item["status"] in {"in_progress", "ready", "validation_required", "ready_for_review", "approved"}
            for item in subset
        ):
            state = "current"
        else:
            state = "pending"
        out.append({"stage": stage, "state": state, "count": len(subset)})
    # Align delivery stage into timeline marker when present.
    if delivery and delivery.get("stage"):
        mapped = {
            "ingest": "requirements",
            "architecture": "architecture",
            "terraform": "infrastructure",
            "plan": "infrastructure",
            "apply": "deployment",
            "code": "cicd",
            "done": "deployment",
        }.get(str(delivery["stage"]))
        if mapped:
            for row in out:
                if row["stage"] == mapped and row["state"] == "pending":
                    row["state"] = "current"
                    break
    return out


def _summary(
    bars: dict[str, dict[str, Any]],
    blockers: list[dict[str, Any]],
    items: list[dict[str, Any]],
    readiness: dict[str, Any],
    architecture_status: str = "",
    delivery: dict[str, Any] | None = None,
) -> str:
    arch = bars.get("architecture", {}).get("percent", 0)
    if architecture_status == "ready" and arch == 0:
        arch_line = "Architecture proposal is ready; implementation tasks are not complete yet."
    elif architecture_status == "generating":
        arch_line = "Architecture proposal is still generating."
    elif architecture_status == "failed":
        arch_line = "Architecture proposal failed and needs a retry."
    else:
        arch_line = f"The architecture is {arch}% complete."
    lines = [arch_line]
    if delivery and delivery.get("stage_label"):
        lines.append(f"Delivery is on {delivery['stage_label']}.")
    lines.append(
        f"{sum(1 for item in items if item['status']=='blocked')} infrastructure/delivery tasks are blocked."
        if any(item["status"] == "blocked" for item in items)
        else "No delivery tasks are currently blocked."
    )
    crit = [item for item in blockers if item["level"] in {"critical", "high"}]
    if crit:
        lines.append("Highest blockers: " + "; ".join(item["title"] for item in crit[:3]) + ".")
    lines.append(
        "Production deployment is blocked." if not readiness["ready"] else "Production readiness gates are currently passing."
    )
    failed = [check["name"] for check in readiness["checks"] if not check["ok"]]
    if failed:
        lines.append("Still required: " + ", ".join(failed[:6]) + ".")
    repair = dict((delivery or {}).get("terraform_repair") or {})
    if repair.get("status") in {"running", "failed", "exhausted"}:
        lines.append(
            f"Terraform repair {repair.get('status')} "
            f"({repair.get('attempt') or 0}/{repair.get('max_attempts') or 4})."
        )
    return " ".join(lines)

