"""Skill taxonomy, registry, wiki layout, and Skill.run with mocked LLM."""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

import pytest

from app.skills import (
    WORKFLOW_SAFE,
    action_class_for,
    blast_radius_for,
    is_workflow_safe,
    registry,
    remediation_class_for,
)
from app.skills.base import AgenticSkill, Skill, SkillRegistry, SkillResult
from app.skills.wiki_format import wiki_page


@pytest.mark.unit
def test_every_registered_skill_has_classification_except_architect():
    from app.skills.classification import SKILL_ACTION_CLASS

    names = {skill.name for skill in registry.all()}
    assert "solution_architect" in names
    assert "solution_architect" not in WORKFLOW_SAFE
    for skill in registry.all():
        if skill.name == "solution_architect":
            continue
        assert skill.name in SKILL_ACTION_CLASS


@pytest.mark.unit
def test_workflow_safe_matches_read_diagnose():
    from app.skills.classification import SKILL_ACTION_CLASS

    for name, cls in SKILL_ACTION_CLASS.items():
        assert is_workflow_safe(name) is (cls == "read_diagnose")
    assert action_class_for("unknown-skill") == "read_diagnose"
    assert remediation_class_for("unknown-skill") == "config_code_change"
    assert blast_radius_for("unknown-skill") == "medium"


@pytest.mark.unit
def test_registry_rejects_empty_and_duplicate_names():
    local = SkillRegistry()
    skill = Skill()
    skill.name = "demo"
    local.register(skill)
    with pytest.raises(ValueError, match="Duplicate"):
        local.register(skill)
    empty = Skill()
    empty.name = ""
    with pytest.raises(ValueError, match="non-empty"):
        local.register(empty)
    assert local.get("missing") is None
    assert local.get("demo") is skill
    assert local.tools()[0]["function"]["name"] == "demo"


@pytest.mark.unit
def test_skill_prompt_assembly_and_run():
    skill = Skill()
    skill.name = "demo"
    skill.system_prompt = "You are a tester."
    skill.json_output = True
    prompt = skill.build_user_prompt({"input": "abc", "extra": "z"})
    assert "### Input" in prompt
    assert skill.build_user_prompt({}) == "(no input provided)"
    completion = SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content='{"ok":true}'))]
    )
    with patch("app.skills.base.azure_client.chat", return_value=completion):
        with patch("app.skills.base.Skill.build_messages", return_value=[{"role": "user", "content": "x"}]):
            result = skill.run({"input": "abc"})
    assert isinstance(result, SkillResult)
    assert result.skill == "demo"
    assert "ok" in result.content
    with patch("app.skills.base.azure_client.chat", return_value=completion):
        with patch("app.skills.base.Skill.build_messages", return_value=[{"role": "user", "content": "x"}]):
            events = list(skill.stream_events({"input": "abc"}))
    assert events[-1]["type"] == "final"


@pytest.mark.unit
def test_agentic_skill_requires_stream_events():
    class Incomplete(AgenticSkill):
        name = "incomplete"

    with pytest.raises(NotImplementedError):
        Incomplete().run({"input": "x"})


@pytest.mark.unit
def test_wiki_page_list_and_string_bodies():
    page = wiki_page(
        "Demo",
        "Overview text",
        does=["does one"],
        when=["when a"],
        how=["how a"],
        uses="uses text",
        output=["json"],
        safety="read only",
        related=["other"],
        maps_to="operate",
        extra="more",
    )
    assert "## Demo" in page
    assert "### What it does" in page
    assert "- does one" in page
    assert "uses text" in page
    assert "more" in page


@pytest.mark.unit
def test_registered_skills_have_metadata():
    assert len(registry.all()) >= 20
    for skill in registry.all():
        assert skill.name
        assert skill.description
        assert skill.wiki
        assert isinstance(skill.triggers, list)
        tool = skill.as_tool()
        assert tool["type"] == "function"
        assert tool["function"]["name"] == skill.name
