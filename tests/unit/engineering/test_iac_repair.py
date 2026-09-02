"""Azure OpenAI Terraform repair context and safe file updates."""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

import pytest

from app.platform.engineering import iac_repair


@pytest.mark.unit
def test_redact_and_existing_context_keep_turns():
    text = iac_repair.redact("ARM_CLIENT_SECRET=super-secret password=hunter2 ok")
    assert "super-secret" not in text
    assert "hunter2" not in text
    ctx = iac_repair.existing_context(
        {
            "terraform_repair": {
                "status": "failed",
                "turns": [{"phase": "init", "diagnosis": "old fix", "files": ["providers.tf"]}],
            }
        }
    )
    assert ctx["turns"][0]["diagnosis"] == "old fix"
    assert "no prior" in iac_repair.turns_for_prompt([])
    assert "old fix" in iac_repair.turns_for_prompt(ctx["turns"])


@pytest.mark.unit
def test_propose_fix_returns_safe_filenames():
    completion = SimpleNamespace(
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(
                    content='{"diagnosis":"pin provider","files":{"../evil.tf":"x","providers.tf":"terraform {}"},"unfixable":false}'
                )
            )
        ]
    )
    with patch("app.platform.engineering.iac_repair.app_config.get_azure_config", return_value=SimpleNamespace(configured=True)):
        with patch("app.platform.engineering.iac_repair.azure_client.chat", return_value=completion):
            proposal = iac_repair.propose_fix(
                phase="init",
                error="missing provider",
                files={"providers.tf": "terraform {}"},
                architecture={"cloud": "azure"},
                turns=[],
            )
    assert proposal["diagnosis"] == "pin provider"
    assert proposal["files"]["providers.tf"] == "terraform {}"
    assert "evil.tf" in proposal["files"]
    assert "../evil.tf" not in proposal["files"]


@pytest.mark.unit
def test_apply_file_updates_skips_unsafe_and_updates_existing():
    existing = SimpleNamespace(
        filename="providers.tf",
        name="providers.tf",
        content_text="old",
        origin="generated",
        version=1,
        updated_at=None,
    )

    class Session:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def scalars(self, _stmt):
            return SimpleNamespace(all=lambda: [existing])

        def add(self, _row):
            raise AssertionError("should update existing row")

        def commit(self):
            self.committed = True

    with patch("app.platform.engineering.iac_repair.SessionLocal", return_value=Session()):
        changed = iac_repair.apply_file_updates(
            "p1",
            "r1",
            {
                "../escape.tf": "bad",
                "providers.tf": "terraform { required_version = \">= 1.5.0\" }",
                "notes.txt": "ignore",
            },
        )
    assert changed == ["providers.tf"]
    assert "required_version" in existing.content_text
    assert existing.origin == "azure_openai_repair"
    assert existing.version == 2


@pytest.mark.unit
def test_record_turn_caps_history():
    turns = []
    for i in range(20):
        turns = iac_repair.record_turn(
            turns,
            phase="plan",
            attempt=i,
            error=f"err-{i}",
            diagnosis=f"fix-{i}",
            files=["main.tf"],
        )
    assert len(turns) == iac_repair.MAX_TURNS
    assert turns[0]["diagnosis"] == "fix-4"
    assert turns[-1]["diagnosis"] == "fix-19"


@pytest.mark.unit
def test_repair_hints_empty_version_list_points_at_region_not_version_toggle():
    error = (
        "ParameterOutOfRange: The value of the 'Version' should be in: []. "
        "Verify that the specified parameter value is correct."
    )
    hints = iac_repair.repair_hints(
        error,
        turns=[{"diagnosis": "removed version because Azure listed none"}],
    )
    assert "eastus2" in hints
    assert "Keep an explicit" in hints
    required = iac_repair.repair_hints("Error: `version` is required when `create_mode` is `Default`")
    assert "Put version" in required
    conflict = iac_repair.repair_hints(
        "InvalidResourceLocation: The resource 'psql-infralens' already exists in location 'eastus2' "
        "in resource group 'rg-infralens-prod'."
    )
    assert "existing region" in conflict
    destroy = iac_repair.repair_hints("Resource has lifecycle prevent_destroy")
    assert "prevent_destroy" in destroy
    assert iac_repair.repair_hints("unrelated") == ""
