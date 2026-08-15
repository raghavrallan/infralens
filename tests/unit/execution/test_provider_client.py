"""CLI read client timeout and success paths with mocked execution service."""
from __future__ import annotations

from unittest.mock import patch

import pytest

from app.execution import provider_client


@pytest.mark.unit
def test_read_environment_success_json():
    with patch(
        "app.execution.provider_client.service.create_action",
        return_value={"id": "a1"},
    ):
        with patch(
            "app.execution.provider_client.service.get_action",
            return_value={
                "status": "succeeded",
                "result": {"stdout": '{"account":"1"}'},
            },
        ):
            text = provider_client.read_environment("p1", "azure", timeout=1)
    assert '"account"' in text


@pytest.mark.unit
def test_read_environment_failure_and_empty_stdout():
    with patch(
        "app.execution.provider_client.service.create_action",
        return_value={"id": "a1"},
    ):
        with patch(
            "app.execution.provider_client.service.get_action",
            return_value={"status": "failed", "error": "boom"},
        ):
            with pytest.raises(RuntimeError, match="boom"):
                provider_client.read_environment("p1", "aws", timeout=1)
        with patch(
            "app.execution.provider_client.service.get_action",
            return_value={"status": "succeeded", "result": {"stdout": ""}},
        ):
            with pytest.raises(RuntimeError, match="no evidence"):
                provider_client.read_environment("p1", "github", timeout=1)


@pytest.mark.unit
def test_read_environment_timeout(monkeypatch):
    monkeypatch.setattr("app.execution.provider_client.time.sleep", lambda _s: None)
    monotonic = iter([0.0, 0.0, 50.0])
    monkeypatch.setattr(
        "app.execution.provider_client.time.monotonic", lambda: next(monotonic)
    )
    with patch(
        "app.execution.provider_client.service.create_action",
        return_value={"id": "a1"},
    ):
        with patch(
            "app.execution.provider_client.service.get_action",
            return_value={"status": "queued"},
        ):
            with pytest.raises(TimeoutError):
                provider_client.read_environment("p1", "azure", timeout=1)
