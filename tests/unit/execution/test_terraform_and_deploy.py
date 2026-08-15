"""Terraform markdown extraction, plan summary, and path safety."""
from __future__ import annotations

from pathlib import Path

import pytest

from app.execution.deploy_orchestrator import build_deploy_plan
from app.execution.terraform_runner import (
    blast_radius_for_plan,
    extract_files_from_markdown,
    parse_plan_summary,
    workspace_dir,
    write_files,
)


@pytest.mark.unit
def test_extract_files_from_markdown_fences_and_headings():
    md = """
```hcl file=main.tf
resource "null_resource" "x" {}
```

### vars.tf
```terraform
variable "name" {}
```
"""
    files = extract_files_from_markdown(md)
    assert "main.tf" in files
    assert "vars.tf" in files
    assert extract_files_from_markdown("") == {}


@pytest.mark.unit
def test_parse_plan_summary_and_blast_radius():
    missing = parse_plan_summary("no counts")
    assert missing["add"] is None
    text = "Plan: 2 to add, 1 to change, 0 to destroy."
    summary = parse_plan_summary(text)
    assert summary["add"] == 2
    assert blast_radius_for_plan({"add": 1, "change": 0, "destroy": 0}) == "low"
    assert blast_radius_for_plan({"add": 0, "change": 0, "destroy": 5}) == "high"
    assert blast_radius_for_plan({"add": 0, "change": 6, "destroy": 1}) == "medium"


@pytest.mark.unit
def test_workspace_rejects_unsafe_names_and_paths(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "app.execution.terraform_runner._WORKSPACE_ROOT", tmp_path
    )
    with pytest.raises(ValueError, match="Invalid"):
        workspace_dir("p1", "../evil")
    root = write_files("p1", {"main.tf": "resource \"x\" \"y\" {}"})
    assert (root / "main.tf").exists()
    with pytest.raises(ValueError, match="Unsafe"):
        write_files("p1", {"../escape.tf": "x"})


@pytest.mark.unit
def test_build_deploy_plan_strategies():
    all_at_once = build_deploy_plan("p1", strategy="all_at_once")
    names = [s.name for s in all_at_once.stages]
    assert names[0] == "lint_validate"
    assert "rollback_ready" in names
    canary = build_deploy_plan("p1", strategy="canary", canary_percent=20)
    assert any(s.name == "canary" for s in canary.stages)
    assert canary.canary_percent == 20
    blue = build_deploy_plan("p1", strategy="blue_green")
    assert any(s.name == "switch" for s in blue.stages)
    fallback = build_deploy_plan("p1", strategy="nope")
    assert fallback.strategy == "all_at_once"
    assert fallback.to_dict()["project_id"] == "p1"
