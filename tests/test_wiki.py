"""Wiki pages exist, are detailed, and catalog order is A–Z."""
from __future__ import annotations

from app.main import _skill_sort_key, list_skills
from app.skills import registry
from app.skills.docs import PAGES

REQUIRED_HEADINGS = (
    "### What it does",
    "### When to use it",
    "### How to run it",
    "### Inputs and connections",
    "### What you get back",
    "### Safety and limits",
    "### Related skills",
    "### Maps to",
)


def test_wiki_pages_cover_every_registered_skill():
    names = {skill.name for skill in registry.all()}
    assert names == set(PAGES)


def test_every_skill_has_detailed_wiki():
    for skill in registry.all():
        for heading in REQUIRED_HEADINGS:
            assert heading in skill.wiki, f"{skill.name} missing {heading}"
        assert f"/{skill.name}" in skill.wiki
        assert len(skill.wiki) > 800, f"{skill.name} wiki is too short"


def test_skills_api_is_sorted_az():
    catalog = list_skills()
    keys = [_skill_sort_key(item) for item in catalog]
    assert keys == sorted(keys)
    assert catalog[0].name == "cloud_posture"
    assert catalog[-1].name == "vuln_triage"
