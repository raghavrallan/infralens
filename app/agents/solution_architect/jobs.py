"""RQ job: generate a delivery-run architecture proposal."""
from __future__ import annotations

from typing import Any

from app.core.db import DeliveryRun, SessionLocal, _now


def generate_architecture(delivery_run_id: str) -> dict[str, Any]:
    from app.agents.solution_architect.graph import invoke_architect
    from app.core.db import init_db

    init_db()
    with SessionLocal() as session:
        row = session.get(DeliveryRun, delivery_run_id)
        if row is None:
            return {"ok": False, "error": "missing run"}
        artifacts = dict(row.artifacts or {})
        docs = str(artifacts.get("docs") or artifacts.get("requirements") or "")
        project_id = row.project_id
        artifacts["architecture_status"] = "generating"
        row.artifacts = artifacts
        row.updated_at = _now()
        session.commit()

    try:
        final = invoke_architect(
            {
                "objective": docs or "Design the architecture for the ingested requirements.",
                "project_id": project_id,
                "plan_only": True,
                "source": "delivery",
                "thread_id": f"delivery:{delivery_run_id}",
            },
            chat_id=f"delivery:{delivery_run_id}",
        )
        status = "ready"
        proposal = {
            "summary": (final.get("reply") or "")[:400],
            "hld": final.get("reply") or "",
            "components": [step.get("skill") for step in (final.get("plan") or [])],
            "notes": docs[:2000],
            "accepted": False,
            "tier": final.get("tier"),
            "mode": final.get("architect_mode"),
            "assumptions_included": True,
        }
    except Exception as exc:  # noqa: BLE001
        status = "failed"
        proposal = {
            "summary": f"Architecture generation failed: {exc}",
            "components": [],
            "notes": docs[:2000],
            "accepted": False,
        }

    with SessionLocal() as session:
        row = session.get(DeliveryRun, delivery_run_id)
        if row is None:
            return {"ok": False}
        artifacts = dict(row.artifacts or {})
        artifacts["architecture_status"] = status
        artifacts["architecture_proposal"] = proposal
        row.artifacts = artifacts
        row.updated_at = _now()
        session.commit()
    return {"ok": status == "ready"}
