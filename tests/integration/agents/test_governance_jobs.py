"""Architect governance, jobs, and LLM helpers."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

import app.skills  # noqa: F401  break architect circular import
from app.agents.solution_architect import governance, jobs, llm


@pytest.mark.unit
def test_architect_llm_requires_config_and_returns_empty_callbacks():
    cfg = MagicMock(configured=False)
    with patch("app.agents.solution_architect.llm.get_azure_config", return_value=cfg):
        with pytest.raises(RuntimeError, match="not configured"):
            llm.get_architect_llm()
    with patch("app.agents.solution_architect.llm.observability.tracing_enabled", return_value=False):
        assert llm.langchain_callbacks() == []
        config = llm.invoke_config()
        assert config["callbacks"] == []


@pytest.mark.integration
def test_governance_upsert_list_and_persist(require_db, org_with_project):
    project_id = org_with_project["project"]["id"]
    workflow_id = governance.ensure_architect_workflow(project_id)
    assert workflow_id
    assert governance.ensure_architect_workflow(project_id) == workflow_id
    run_id = governance.upsert_run(
        thread_id="thread-gov",
        project_id=project_id,
        user_id="u1",
        objective="queue",
        source="chat",
        tier="T1",
        mode="greenfield",
        status="awaiting_input",
        pending_question="what region?",
        checkpoint={"objective": "queue", "pending_question": "what region?"},
    )
    paused = governance.load_paused("thread-gov")
    assert paused is not None
    assert paused["pending_question"] == "what region?"
    assert governance.load_paused("missing") is None
    gated = governance.persist_decisions(
        run_id=run_id,
        project_id=project_id,
        decisions=[
            {
                "title": "Use managed queue",
                "decision": "Add Service Bus",
                "risk_class": "config_code_change",
                "blast_radius": "low",
                "options_considered": [{"name": "SB", "tradeoffs": "managed"}],
            }
        ],
    )
    assert gated
    listed = governance.list_runs(project_id)
    assert isinstance(listed, list)
    assert governance.high_gate_unjustified(
        [
            {
                "recommended": True,
                "risk_class": "irreversible_high_blast",
                "blast_radius": "high",
                "justified": False,
            }
        ]
    )
    assert not governance.high_gate_unjustified(
        [{"recommended": True, "risk_class": "read_diagnose", "blast_radius": "low", "justified": True}]
    )


@pytest.mark.integration
def test_persist_decisions_accepts_prose_blast_radius(require_db, org_with_project):
    """LLM verify often writes a sentence into blast_radius (varchar(16))."""
    from sqlalchemy import select

    from app.core.db import ArchitectureDecision, Finding, SessionLocal

    project_id = org_with_project["project"]["id"]
    run_id = governance.upsert_run(
        thread_id="thread-prose-blast",
        project_id=project_id,
        user_id="u1",
        objective="InfraLens prod",
        source="chat",
        tier="T2",
        mode="brownfield",
        status="running",
    )
    gated = governance.persist_decisions(
        run_id=run_id,
        project_id=project_id,
        decisions=[
            {
                "title": "Adopt a private, managed data plane for InfraLens",
                "context": (
                    "InfraLens requires production isolation in a brownfield Azure "
                    "subscription with unrelated existing resources."
                ),
                "options_considered": [
                    "Use shared existing infrastructure and public endpoints",
                    "Build a private data plane with managed services",
                ],
                "decision": (
                    "Choose the private data plane with managed secrets and "
                    "isolated persistence."
                ),
                "consequences": "Improves isolation and keeps secrets out of code.",
                "risk_class": "medium",
                "blast_radius": (
                    "InfraLens-only resource group and dependent managed services"
                ),
                "severity": "medium",
                "recommended_action": "Use a dedicated RG with private Postgres and Redis.",
            }
        ],
    )
    assert gated
    assert gated[0]["gate"] == "human_approval"
    with SessionLocal() as session:
        row = session.scalar(
            select(ArchitectureDecision).where(ArchitectureDecision.run_id == run_id)
        )
        assert row is not None
        assert row.blast_radius == "medium"
        assert row.risk_class == "config_code_change"
        finding = session.scalar(
            select(Finding).where(Finding.title.contains("private, managed data plane"))
        )
        assert finding is not None
        assert finding.blast_radius == "medium"


@pytest.mark.integration
def test_persist_decisions_one_finding_per_adr_title(require_db, org_with_project):
    from sqlalchemy import select

    from app.core.db import Finding, SessionLocal

    project_id = org_with_project["project"]["id"]
    run_id = governance.upsert_run(
        thread_id="thread-multi-adr",
        project_id=project_id,
        user_id="u1",
        objective="InfraLens prod",
        source="chat",
        tier="T2",
        mode="greenfield",
        status="running",
    )
    gated = governance.persist_decisions(
        run_id=run_id,
        project_id=project_id,
        decisions=[
            {
                "title": "Adopt a private, managed data plane for InfraLens",
                "decision": "Private Postgres, Redis, and Key Vault.",
                "risk_class": "config_code_change",
                "blast_radius": "medium",
            },
            {
                "title": "Choose a bounded, right-sized isolated deployment",
                "decision": "Dedicated resource group, no shared EQIP estate.",
                "risk_class": "config_code_change",
                "blast_radius": "low",
            },
        ],
    )
    assert len(gated) == 2
    with SessionLocal() as session:
        titles = set(
            session.scalars(
                select(Finding.title).where(
                    Finding.project_id == project_id,
                    Finding.skill == "solution_architect",
                    Finding.title.in_(
                        {
                            "Adopt a private, managed data plane for InfraLens",
                            "Choose a bounded, right-sized isolated deployment",
                        }
                    ),
                )
            )
        )
    assert titles == {
        "Adopt a private, managed data plane for InfraLens",
        "Choose a bounded, right-sized isolated deployment",
    }


@pytest.mark.integration
def test_stale_architecture_run_and_persist_failure(require_db, org_with_project):
    from datetime import datetime, timedelta, timezone

    from sqlalchemy import update

    from app.core.db import ArchitectureRun, SessionLocal
    from app.intelligence import workflows as intel

    project_id = org_with_project["project"]["id"]
    run_id = governance.upsert_run(
        thread_id="thread-stale",
        project_id=project_id,
        user_id="u1",
        objective="stuck",
        source="chat",
        tier="T1",
        mode="greenfield",
        status="running",
    )
    old = datetime.now(timezone.utc) - timedelta(days=13)
    with SessionLocal() as session:
        session.execute(
            update(ArchitectureRun)
            .where(ArchitectureRun.id == run_id)
            .values(created_at=old, updated_at=old, status="running")
        )
        session.commit()
    assert governance.reap_stale_architecture_runs(project_id) >= 1
    listed = governance.list_runs(project_id)
    stale = next(item for item in listed if item["id"] == run_id)
    assert stale["status"] == "failed"

    live_id = governance.upsert_run(
        thread_id="thread-persist-fail",
        project_id=project_id,
        user_id="u1",
        objective="persist",
        source="chat",
        tier="T1",
        mode="greenfield",
        status="running",
    )
    with patch(
        "app.agents.solution_architect.governance.store.save_findings",
        side_effect=RuntimeError("write failed"),
    ):
        with pytest.raises(RuntimeError, match="write failed"):
            governance.persist_decisions(
                run_id=live_id,
                project_id=project_id,
                decisions=[{"title": "queue", "decision": "Add a queue"}],
            )
    runs = intel.list_runs(project_id)
    failed = [row for row in runs if row["workflow_name"] == governance.ARCHITECT_WORKFLOW_NAME]
    assert failed
    assert any(row["status"] == "failed" for row in failed)


@pytest.mark.integration
def test_generate_architecture_missing_and_success(require_db, org_with_project):
    assert jobs.generate_architecture("missing")["ok"] is False
    from app.platform import delivery

    run = delivery.create_run(org_with_project["project"]["id"], created_by="tester")
    configured = MagicMock(configured=True)
    with patch("app.core.config.get_azure_config", return_value=configured):
        with patch(
            "app.agents.solution_architect.graph.stream_architect",
            return_value=iter(
                [
                    {"type": "status", "text": "Clarifying the ask"},
                    {
                        "type": "final",
                        "reply": "HLD",
                        "plan": [{"skill": "infrastructure_architect"}],
                        "tier": "T1",
                        "architecture": {"cloud": "azure", "components": [{"name": "Compute platform"}]},
                    },
                ]
            ),
        ):
            result = jobs.generate_architecture(run["id"])
        assert result["ok"] is True
        loaded = delivery.get_run(run["id"])
        assert loaded["artifacts"]["architecture_status"] == "ready"
        assert loaded["artifacts"].get("architecture_progress") == "Clarifying the ask"
        with patch(
            "app.agents.solution_architect.graph.stream_architect",
            side_effect=RuntimeError("llm down"),
        ):
            failed = jobs.generate_architecture(run["id"])
        assert failed["ok"] is False
    missing_llm = delivery.create_run(org_with_project["project"]["id"], created_by="tester")
    with patch(
        "app.core.config.get_azure_config",
        return_value=MagicMock(configured=False),
    ):
        blocked = jobs.generate_architecture(missing_llm["id"])
    assert blocked["ok"] is False
    assert delivery.get_run(missing_llm["id"])["artifacts"]["architecture_status"] == "failed"


@pytest.mark.integration
def test_stale_delivery_architecture_job(require_db, org_with_project):
    from datetime import datetime, timedelta, timezone

    from sqlalchemy import update

    from app.core.db import DeliveryRun, SessionLocal
    from app.platform import delivery

    run = delivery.create_run(org_with_project["project"]["id"], created_by="tester")
    old = datetime.now(timezone.utc) - timedelta(days=13)
    with SessionLocal() as session:
        row = session.get(DeliveryRun, run["id"])
        row.artifacts = {
            "architecture_status": "generating",
            "architecture_proposal": {"summary": "Generating…", "accepted": False},
        }
        session.commit()
        session.execute(
            update(DeliveryRun)
            .where(DeliveryRun.id == run["id"])
            .values(created_at=old, updated_at=old)
        )
        session.commit()
    assert delivery.reap_stale_architecture_jobs(org_with_project["project"]["id"]) >= 1
    loaded = delivery.get_run(run["id"])
    assert loaded["artifacts"]["architecture_status"] == "failed"
