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
def test_generate_architecture_missing_and_success(require_db, org_with_project):
    assert jobs.generate_architecture("missing")["ok"] is False
    from app.platform import delivery

    run = delivery.create_run(org_with_project["project"]["id"], created_by="tester")
    with patch(
        "app.agents.solution_architect.graph.invoke_architect",
        return_value={"reply": "HLD", "plan": [{"skill": "infrastructure_architect"}], "tier": "T1"},
    ):
        result = jobs.generate_architecture(run["id"])
    assert result["ok"] is True
    loaded = delivery.get_run(run["id"])
    assert loaded["artifacts"]["architecture_status"] == "ready"
    with patch(
        "app.agents.solution_architect.graph.invoke_architect",
        side_effect=RuntimeError("llm down"),
    ):
        failed = jobs.generate_architecture(run["id"])
    assert failed["ok"] is False
