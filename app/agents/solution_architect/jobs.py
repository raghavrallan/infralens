"""RQ job: generate a delivery-run architecture proposal."""
from __future__ import annotations

from typing import Any

from app.core.db import DeliveryRun, SessionLocal, _now


def generate_architecture(delivery_run_id: str) -> dict[str, Any]:
    from app.core.db import init_db

    init_db()
    from app.core.config import get_azure_config

    with SessionLocal() as session:
        row = session.get(DeliveryRun, delivery_run_id)
        if row is None:
            return {"ok": False, "error": "missing run"}
        artifacts = dict(row.artifacts or {})
        docs = str(artifacts.get("docs") or artifacts.get("requirements") or "")
        project_id = row.project_id
        if not get_azure_config().configured:
            artifacts["architecture_status"] = "failed"
            artifacts["architecture_proposal"] = {
                "summary": (
                    "Architecture generation failed: Azure OpenAI is not configured. "
                    "Open Settings and add the platform endpoint and API key."
                ),
                "components": [],
                "notes": docs[:2000],
                "accepted": False,
            }
            row.artifacts = artifacts
            row.updated_at = _now()
            session.commit()
            return {"ok": False, "error": "Azure OpenAI is not configured"}
        artifacts["architecture_status"] = "generating"
        row.artifacts = artifacts
        row.updated_at = _now()
        session.commit()

    try:
        from app.agents.solution_architect.graph import stream_architect

        final: dict[str, Any] = {}
        for event in stream_architect(
            {
                "objective": docs or "Design the architecture for the ingested requirements.",
                "project_id": project_id,
                "plan_only": True,
                "source": "delivery",
                "thread_id": f"delivery:{delivery_run_id}",
            },
            chat_id=f"delivery:{delivery_run_id}",
        ):
            if event.get("type") == "status" and event.get("text"):
                _write_progress(delivery_run_id, str(event["text"]))
            if event.get("type") == "final":
                final = event
        if not final:
            raise RuntimeError("Architecture pipeline returned no result")
        status = "ready"
        architecture = final.get("architecture") if isinstance(final.get("architecture"), dict) else {}
        component_names = [
            str(item.get("name") or "")
            for item in (architecture.get("components") or [])
            if isinstance(item, dict) and item.get("name")
        ]
        proposal = {
            "summary": (final.get("reply") or "")[:400],
            "hld": final.get("reply") or "",
            "components": component_names
            or [step.get("skill") for step in (final.get("plan") or [])],
            "architecture": architecture,
            "mermaid": final.get("mermaid") or architecture.get("mermaid") or "",
            "notes": docs[:2000],
            "accepted": False,
            "tier": final.get("tier") or architecture.get("tier"),
            "mode": final.get("architect_mode") or architecture.get("mode"),
            "assumptions_included": True,
            "analysis": architecture.get("analysis") or {},
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


def _write_progress(delivery_run_id: str, text: str) -> None:
    with SessionLocal() as session:
        row = session.get(DeliveryRun, delivery_run_id)
        if row is None:
            return
        artifacts = dict(row.artifacts or {})
        artifacts["architecture_progress"] = text[:240]
        row.artifacts = artifacts
        row.updated_at = _now()
        session.commit()
