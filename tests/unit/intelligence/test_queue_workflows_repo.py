"""Intelligence queue URLs, workflow time bounds, and repo path classification."""
from __future__ import annotations

from datetime import date, timedelta
from unittest.mock import patch

import pytest

from app.core.db import get_database_url
from app.intelligence import queue as intel_queue
from app.intelligence.repo_analyzer import _classify_path, _framework_hint, analyze_repositories
from app.intelligence.workflows import MODULES, time_range_bounds
from app.agents.solution_architect.state import empty_state, infer_tier


@pytest.mark.unit
def test_get_database_url_reads_env(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg2://x:y@localhost/z")
    assert "localhost/z" in get_database_url()


@pytest.mark.unit
def test_intelligence_queue_url_and_enqueue(monkeypatch):
    monkeypatch.setenv("REDIS_URL", "redis://example:6379/2")
    intel_queue.get_redis.cache_clear()
    intel_queue.get_queue.cache_clear()
    assert intel_queue.get_redis_url() == "redis://example:6379/2"
    fake_queue = type("Q", (), {"enqueue": staticmethod(lambda *a, **k: None)})()
    with patch("app.intelligence.queue.get_queue", return_value=fake_queue):
        intel_queue.enqueue_run("run-1")
        intel_queue.enqueue_architecture("del-1")
    intel_queue.get_redis.cache_clear()
    intel_queue.get_queue.cache_clear()


@pytest.mark.unit
def test_time_range_bounds_presets_and_custom():
    since, until = time_range_bounds("all")
    assert since is None and until is None
    since, until = time_range_bounds("7d")
    assert since is not None and until is None
    since, until = time_range_bounds(
        "custom", start_date=date(2026, 8, 1), end_date=date(2026, 8, 7)
    )
    assert since.day == 1
    assert until.day == 8


@pytest.mark.unit
def test_modules_catalog_has_six_keys():
    assert set(MODULES) == {
        "pipeline_intelligence",
        "release_confidence",
        "iac",
        "incident_response",
        "security_patch",
        "finops",
    }


@pytest.mark.unit
def test_repo_path_classification_and_frameworks():
    assert "iac" in _classify_path("infra/main.tf")
    assert "pipeline" in _classify_path(".github/workflows/ci.yml")
    assert "backend" in _classify_path("requirements.txt")
    assert "frontend" in _classify_path("next.config.js")
    assert "container" in _classify_path("Dockerfile")
    assert _classify_path("notes.txt") == ["other"]
    assert _framework_hint("app.py", "from fastapi import FastAPI") == "fastapi"
    assert _framework_hint("manage.py", "django") == "django"
    assert _framework_hint("main.tf", "") == "terraform"
    assert _framework_hint("unknown.c", "") == ""


@pytest.mark.unit
def test_analyze_repositories_without_github():
    with patch("app.intelligence.repo_analyzer.github_infra.is_connected", return_value=False):
        with patch(
            "app.intelligence.repo_analyzer.build_existing_context",
            return_value=type("C", (), {"repos": ["acme/app"], "to_dict": lambda self: {}})(),
        ):
            result = analyze_repositories("p1")
    assert result["error"] == "GitHub is not connected"


@pytest.mark.unit
def test_architect_empty_state_and_tier():
    state = empty_state(objective="build pci multi-region platform")
    assert state["tier"] == "T1"
    assert infer_tier("pci multi-region enterprise") == "T3"
    assert infer_tier("split the monolith into microservices") == "T2"
    assert infer_tier("tiny api") == "T1"
