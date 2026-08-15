"""Executor CLI redaction, allowlist, and entrypoint env validation."""
from __future__ import annotations

from unittest.mock import patch

import pytest

from executors.common.entrypoint import main
from executors.common.runner import redact, run_cli


@pytest.mark.unit
def test_redact_masks_tokens_and_passwords():
    text = "Authorization: Bearer supersecrettokenvalue password=hunter2"
    cleaned = redact(text)
    assert "supersecrettokenvalue" not in cleaned
    assert "hunter2" not in cleaned
    assert "[REDACTED]" in cleaned


@pytest.mark.unit
def test_run_cli_rejects_non_provider_executable():
    with pytest.raises(ValueError, match="Only provider"):
        run_cli(["python", "-c", "print(1)"], {})


@pytest.mark.unit
def test_entrypoint_requires_org_and_provider(monkeypatch, capsys):
    monkeypatch.delenv("EXECUTOR_ORG_ID", raising=False)
    monkeypatch.delenv("EXECUTOR_PROVIDER", raising=False)
    assert main([]) == 64
    monkeypatch.setenv("EXECUTOR_ORG_ID", "org-1")
    monkeypatch.setenv("EXECUTOR_PROVIDER", "gcp")
    assert main([]) == 64
    err = capsys.readouterr().err
    assert "EXECUTOR_PROVIDER" in err


@pytest.mark.unit
def test_entrypoint_starts_rq_when_env_valid(monkeypatch):
    monkeypatch.setenv("EXECUTOR_ORG_ID", "org-1")
    monkeypatch.setenv("EXECUTOR_PROVIDER", "azure")
    monkeypatch.setenv("REDIS_URL", "redis://localhost:6379/0")
    with patch("rq.cli.main") as rq_main:
        assert main([]) == 0
        rq_main.assert_called_once()
