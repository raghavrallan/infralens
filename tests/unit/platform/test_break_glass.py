"""Break-glass one-step downgrade without requiring an active DB session."""
from __future__ import annotations

import pytest

from app.intelligence.risk_engine import GATE_ORDER
from app.platform import break_glass


@pytest.mark.unit
def test_downgrade_gate_inactive_is_identity():
    assert break_glass.downgrade_gate("two_person", "p1", active=False) == "two_person"


@pytest.mark.unit
def test_downgrade_gate_one_step_and_floor():
    assert break_glass.downgrade_gate("two_person", "p1", active=True) == "human_approval"
    assert break_glass.downgrade_gate("human_approval", "p1", active=True) == "auto_apply"
    assert break_glass.downgrade_gate("autonomous", "p1", active=True) == "autonomous"
    assert break_glass.downgrade_gate("not-a-gate", "p1", active=True) == "not-a-gate"


@pytest.mark.unit
def test_gate_with_break_glass_payload():
    payload = break_glass.gate_with_break_glass("two_person", "p1", active=True)
    assert payload["original_gate"] == "two_person"
    assert payload["gate"] == "human_approval"
    assert payload["break_glass_applied"] is True
    unchanged = break_glass.gate_with_break_glass("two_person", "p1", active=False)
    assert unchanged["break_glass_applied"] is False
    assert unchanged["gate"] == "two_person"


@pytest.mark.unit
def test_open_session_requires_reason():
    with pytest.raises(ValueError, match="reason"):
        break_glass.open_session("p1", opened_by="lead", reason="short")


@pytest.mark.unit
def test_every_gate_can_downgrade_or_floor():
    for gate in GATE_ORDER:
        result = break_glass.downgrade_gate(gate, "p1", active=True)
        assert result in GATE_ORDER
