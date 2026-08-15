"""Engineering Memory as project knowledge with lifecycle and confidence."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import select

from app.core.db import EngineeringMemory, SessionLocal, _now

CATEGORIES = (
    "architecture",
    "infrastructure",
    "security",
    "database",
    "cloud",
    "cicd",
    "deployment",
    "incident",
    "decision",
    "requirement",
)
STATUSES = ("draft", "verified", "active", "superseded", "archived")
CONFIDENCE = ("high", "medium", "low")


def _iso(value: Any) -> Optional[str]:
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value) if value else None


def _enrich(row: EngineeringMemory) -> dict[str, Any]:
    payload = dict(row.payload or {})
    return {
        "id": row.id,
        "project_id": row.project_id,
        "kind": row.kind,
        "ref_id": row.ref_id,
        "title": payload.get("title") or (row.summary or "")[:120],
        "summary": row.summary,
        "outcome": row.outcome,
        "status": payload.get("status") or ("active" if row.outcome in {"approved", "succeeded", "verified"} else "draft"),
        "confidence": payload.get("confidence") or "medium",
        "source": payload.get("source") or row.kind,
        "category": payload.get("category") or _category_from_kind(row.kind),
        "created_by": payload.get("created_by") or "",
        "last_verified_at": payload.get("last_verified_at"),
        "superseded_by": payload.get("superseded_by") or "",
        "related_adr": payload.get("related_adr") or "",
        "related_task_id": payload.get("related_task_id") or "",
        "related_requirement_id": payload.get("related_requirement_id") or "",
        "payload": payload,
        "created_at": _iso(row.created_at),
        "stale": _is_stale(payload, row.created_at),
    }


def _category_from_kind(kind: str) -> str:
    mapping = {
        "architecture_decision": "decision",
        "action": "infrastructure",
        "finding": "incident",
        "requirement": "requirement",
    }
    return mapping.get(kind or "", "architecture")


def _is_stale(payload: dict[str, Any], created_at: Any) -> bool:
    status = payload.get("status") or ""
    if status in {"superseded", "archived"}:
        return True
    verified = payload.get("last_verified_at")
    stamp = verified or (created_at.isoformat() if created_at else "")
    try:
        when = datetime.fromisoformat(str(stamp).replace("Z", "+00:00"))
    except Exception:
        return False
    age_days = (datetime.now(timezone.utc) - when).days
    return age_days > 90 and status != "verified"


def remember(
    *,
    project_id: str,
    summary: str,
    kind: str = "decision",
    outcome: str = "recorded",
    source: str = "system",
    category: str = "architecture",
    confidence: str = "medium",
    status: str = "active",
    ref_id: str = "",
    created_by: str = "",
    related_adr: str = "",
    related_task_id: str = "",
    extra: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    payload = {
        "title": (summary or "")[:120],
        "status": status if status in STATUSES else "draft",
        "confidence": confidence if confidence in CONFIDENCE else "medium",
        "source": source,
        "category": category if category in CATEGORIES else "architecture",
        "created_by": created_by,
        "related_adr": related_adr,
        "related_task_id": related_task_id,
        **(extra or {}),
    }
    with SessionLocal() as session:
        row = EngineeringMemory(
            id=str(uuid.uuid4()),
            project_id=project_id,
            kind=kind[:32],
            ref_id=(ref_id or "")[:36],
            summary=(summary or "")[:2000],
            outcome=(outcome or "")[:32],
            payload=payload,
        )
        session.add(row)
        session.commit()
        session.refresh(row)
        return _enrich(row)


def list_knowledge(
    project_id: str,
    *,
    category: str = "",
    status: str = "",
    query: str = "",
    limit: int = 80,
) -> list[dict[str, Any]]:
    with SessionLocal() as session:
        rows = session.scalars(
            select(EngineeringMemory)
            .where(EngineeringMemory.project_id == project_id)
            .order_by(EngineeringMemory.created_at.desc())
            .limit(max(1, min(limit, 200)))
        ).all()
    items = [_enrich(row) for row in rows]
    needle = (query or "").strip().lower()
    out: list[dict[str, Any]] = []
    for item in items:
        if category and item["category"] != category:
            continue
        if status and item["status"] != status:
            continue
        if needle and needle not in f"{item['title']} {item['summary']}".lower():
            continue
        out.append(item)
    return out


def get_item(item_id: str) -> Optional[dict[str, Any]]:
    with SessionLocal() as session:
        row = session.get(EngineeringMemory, item_id)
        return _enrich(row) if row else None


def set_status(item_id: str, status: str, *, actor: str = "") -> dict[str, Any]:
    if status not in STATUSES:
        raise ValueError(f"Unknown memory status: {status}")
    with SessionLocal() as session:
        row = session.get(EngineeringMemory, item_id)
        if row is None:
            raise LookupError("Memory entry not found")
        payload = dict(row.payload or {})
        payload["status"] = status
        if status == "verified":
            payload["last_verified_at"] = _now().isoformat()
            payload["verified_by"] = actor
            row.outcome = "verified"
        if status == "archived":
            row.outcome = "archived"
        row.payload = payload
        session.commit()
        session.refresh(row)
        return _enrich(row)


def supersede(old_id: str, *, summary: str, actor: str = "", extra: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    old = get_item(old_id)
    if old is None:
        raise LookupError("Memory entry not found")
    fresh = remember(
        project_id=old["project_id"],
        summary=summary,
        kind=old["kind"],
        outcome="active",
        source="supersede",
        category=old["category"],
        confidence="high",
        status="active",
        created_by=actor,
        extra={"replaces": old_id, **(extra or {})},
    )
    with SessionLocal() as session:
        row = session.get(EngineeringMemory, old_id)
        if row is not None:
            payload = dict(row.payload or {})
            payload["status"] = "superseded"
            payload["superseded_by"] = fresh["id"]
            row.payload = payload
            row.outcome = "superseded"
            session.commit()
    return fresh


def architect_context(project_id: str) -> dict[str, Any]:
    """Facts vs decisions vs assumptions for the Solution Architect."""
    items = list_knowledge(project_id, limit=80)
    facts, decisions, assumptions, conflicts = [], [], [], []
    by_category: dict[str, list[dict[str, Any]]] = {}
    for item in items:
        if item["status"] in {"superseded", "archived"}:
            continue
        bucket = by_category.setdefault(item["category"], [])
        bucket.append(item)
        label = f"[{item['confidence']}/{item['status']}] {item['summary']}"
        if item["kind"] in {"requirement"} or item["category"] == "requirement":
            facts.append(label)
        elif item["kind"] == "architecture_decision" or item["category"] == "decision":
            decisions.append(label)
        elif item["status"] == "draft":
            assumptions.append(label)
        else:
            facts.append(label)
    for category, rows in by_category.items():
        active = [row for row in rows if row["status"] in {"active", "verified"}]
        if len(active) >= 2:
            summaries = {row["summary"].strip().lower()[:80] for row in active}
            if len(summaries) >= 2:
                conflicts.append(
                    {
                        "category": category,
                        "entries": [{"id": row["id"], "summary": row["summary"]} for row in active[:4]],
                    }
                )
    usable = [
        item for item in items
        if item["status"] in {"active", "verified"} and not item["stale"]
    ]
    return {
        "known_facts": facts[:12],
        "previous_decisions": decisions[:12],
        "assumptions": assumptions[:8],
        "conflicts": conflicts,
        "usable": usable[:20],
        "prompt": _prompt(facts, decisions, assumptions, conflicts),
    }


def _prompt(facts: list[str], decisions: list[str], assumptions: list[str], conflicts: list[dict[str, Any]]) -> str:
    lines = ["ENGINEERING MEMORY (do not treat stale/superseded items as current requirements)"]
    lines.append("Known facts:")
    lines.extend(f"- {item}" for item in facts[:8] or ["- none"])
    lines.append("Previous decisions:")
    lines.extend(f"- {item}" for item in decisions[:8] or ["- none"])
    lines.append("Assumptions / unverified:")
    lines.extend(f"- {item}" for item in assumptions[:6] or ["- none"])
    if conflicts:
        lines.append("CONFLICTS — ask the user before choosing:")
        for conflict in conflicts:
            lines.append(f"- {conflict['category']}: " + " vs ".join(e["summary"][:80] for e in conflict["entries"]))
    return "\n".join(lines)
