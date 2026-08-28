"""Risk engine matrix: safety-direction, prod vs non-prod, blast escalation."""
from __future__ import annotations

import pytest

from app.intelligence.risk_engine import (
    GATE_LABELS,
    GATE_ORDER,
    blast_radius_from_severity,
    classify,
)


@pytest.mark.unit
def test_safety_direction_is_never_gated():
    for env in ("dev", "staging", "prod"):
        for blast in ("low", "medium", "high"):
            decision = classify("safety_direction", blast, env)
            assert decision.never_gated is True
            assert decision.gate == "autonomous"
            assert decision.requires_approval is False
            assert decision.two_person is False


@pytest.mark.unit
def test_read_diagnose_is_autonomous_everywhere():
    for env in ("dev", "staging", "prod"):
        decision = classify("read_diagnose", "high", env)
        assert decision.gate == "autonomous"


@pytest.mark.unit
def test_reversible_change_prod_vs_non_prod():
    assert classify("reversible_change", "low", "dev").gate == "autonomous_logged"
    assert classify("reversible_change", "low", "prod").gate == "auto_instant_undo"


@pytest.mark.unit
def test_config_code_change_and_high_blast_escalation():
    assert classify("config_code_change", "medium", "dev").gate == "auto_apply"
    escalated = classify("config_code_change", "high", "dev")
    assert escalated.gate == "human_approval"
    assert "escalated" in escalated.rationale
    prod = classify("config_code_change", "medium", "prod")
    assert prod.requires_approval is True
    assert prod.gate == "human_approval"


@pytest.mark.unit
def test_irreversible_high_blast_two_person_in_prod():
    prod = classify("irreversible_high_blast", "medium", "prod")
    assert prod.gate == "two_person"
    assert prod.two_person is True
    high = classify("irreversible_high_blast", "high", "prod")
    assert high.gate == "two_person"
    non_prod = classify("irreversible_high_blast", "low", "staging")
    assert non_prod.gate == "human_approval"


@pytest.mark.unit
def test_unknown_action_class_defaults_to_human_approval():
    decision = classify("not_a_class", "low", "dev")  # type: ignore[arg-type]
    assert decision.gate == "human_approval"


@pytest.mark.unit
def test_blast_radius_from_severity():
    assert blast_radius_from_severity("low", "critical") == "high"
    assert blast_radius_from_severity("low", "HIGH") == "high"
    assert blast_radius_from_severity("low", "medium") == "medium"
    assert blast_radius_from_severity("medium", "low") == "medium"
    assert blast_radius_from_severity("low", "") == "low"
    assert blast_radius_from_severity("low", None) == "low"  # type: ignore[arg-type]


@pytest.mark.unit
def test_gate_labels_cover_order():
    assert set(GATE_LABELS) == set(GATE_ORDER)


@pytest.mark.unit
def test_normalize_prose_blast_radius_and_swapped_risk_class():
    from app.intelligence.risk_engine import (
        classify,
        normalize_action_class,
        normalize_blast_radius,
    )

    blast = normalize_blast_radius(
        "InfraLens-only resource group and dependent managed services"
    )
    assert blast == "medium"
    assert normalize_blast_radius("high blast across the subscription") == "high"
    assert normalize_blast_radius("LOW") == "low"
    assert normalize_action_class("medium") == "config_code_change"
    assert normalize_action_class("config_code_change") == "config_code_change"
    assert normalize_action_class("irreversible destroy") == "irreversible_high_blast"
    gated = classify("medium", blast, "prod")  # type: ignore[arg-type]
    assert gated.gate == "human_approval"
    assert "medium blast radius" in gated.rationale
