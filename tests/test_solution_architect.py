"""Solution Architect skill is agentic, not auto-routed, not workflow-safe."""
from app.orchestrator import _skill_catalog_text
from app.skills import is_workflow_safe, registry


def test_solution_architect_registered_but_not_auto_or_workflow():
    skill = registry.get("solution_architect")
    assert skill is not None
    assert skill.is_agentic is True
    assert skill.auto_routable is False
    assert is_workflow_safe("solution_architect") is False
    catalog = _skill_catalog_text()
    assert "solution_architect" not in catalog
    assert "infrastructure_architect" in catalog
