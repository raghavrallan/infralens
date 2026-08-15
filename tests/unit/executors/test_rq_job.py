"""Executor RQ job: auth env, preflight, step execution, and claim/finish."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import httpx
import pytest

from executors.common.rq_job import (
    _auth_env,
    _finish,
    _headers,
    _preflight_found_existing,
    _preflight_value,
    _run,
    _run_step,
    _verification_succeeded,
    execute_provider_job,
)
from executors.common.runner import CliResult


@pytest.mark.unit
def test_headers_include_org_when_set(monkeypatch):
    monkeypatch.setenv("EXECUTOR_SERVICE_KEY", "k")
    monkeypatch.setenv("EXECUTOR_PROVIDER", "azure")
    monkeypatch.setenv("EXECUTOR_ORG_ID", "org-1")
    headers = _headers()
    assert headers["X-Executor-Org-Id"] == "org-1"
    assert headers["X-Executor-Provider"] == "azure"


@pytest.mark.unit
def test_auth_env_for_each_provider(tmp_path):
    azure = _auth_env("azure", {}, str(tmp_path))
    assert azure["AZURE_CONFIG_DIR"] == str(tmp_path)
    aws = _auth_env(
        "aws",
        {"access_key_id": "ak", "secret_access_key": "sk", "region": "eu-west-1"},
        str(tmp_path),
    )
    assert aws["AWS_ACCESS_KEY_ID"] == "ak"
    gh = _auth_env("github", {"token": "gho", "repo": "acme/app"}, str(tmp_path))
    assert gh["GH_TOKEN"] == "gho"
    assert gh["GH_REPO"] == "acme/app"
    tf_aws = _auth_env(
        "terraform",
        {"cloud_provider": "aws", "access_key_id": "ak", "secret_access_key": "sk"},
        str(tmp_path),
    )
    assert tf_aws["AWS_ACCESS_KEY_ID"] == "ak"
    tf_az = _auth_env(
        "terraform",
        {
            "cloud_provider": "azure",
            "client_id": "c",
            "client_secret": "s",
            "tenant_id": "t",
            "subscription_id": "sub",
        },
        str(tmp_path),
    )
    assert tf_az["ARM_CLIENT_ID"] == "c"


@pytest.mark.unit
def test_preflight_value_and_existing_resource_detection():
    assert _preflight_value("") == ""
    assert _preflight_value("true") == "true"
    assert _preflight_value("null") == "null" or _preflight_value("null") == ""
    assert _preflight_value("[1, 2]") in {"1\n2", "1\n2".lower()} or "1" in _preflight_value("[1, 2]")
    assert _preflight_value("false") == "false"
    op = {
        "provider": "azure",
        "args": ["group", "create", "--name", "demo"],
        "skip_if_exists": True,
        "preflight_expect": "false",
    }
    existing = CliResult(0, "true", "")
    assert _preflight_found_existing(op, existing) is True
    absent = CliResult(0, "false", "")
    assert _preflight_found_existing(op, absent) is False
    assert _verification_succeeded({"args": ["group", "delete"]}, CliResult(0, "{}", "")) is True


@pytest.mark.unit
def test_run_step_success_preflight_fail_and_verify():
    op = {
        "executable": "az",
        "args": ["account", "show"],
        "target": "identity",
        "preflight": [],
        "verify": [],
    }
    with patch("executors.common.rq_job.validate_operation", return_value=op):
        with patch("executors.common.rq_job.command_argv", return_value=["az", "account", "show"]):
            with patch(
                "executors.common.rq_job.run_cli",
                return_value=CliResult(0, "{}", ""),
            ):
                status, result, error = _run_step("azure", op, {}, lambda *_a: None, lambda: False)
    assert status == "succeeded"
    assert error == ""
    with patch("executors.common.rq_job.validate_operation", return_value=op):
        with patch("executors.common.rq_job.command_argv", return_value=["az", "group", "show"]):
            with patch(
                "executors.common.rq_job.run_cli",
                return_value=CliResult(1, "", "missing"),
            ):
                failed_op = {**op, "preflight": ["group", "show"]}
                status, _result, error = _run_step(
                    "azure", failed_op, {}, lambda *_a: None, lambda: False
                )
    assert status == "failed"
    assert "Preflight" in error
    write_op = {
        "executable": "az",
        "args": ["group", "create", "--name", "demo"],
        "target": "rg/demo",
        "preflight": [],
        "verify": ["group", "show", "--name", "demo"],
    }
    results = [
        CliResult(0, "created", ""),
        CliResult(0, "exists", ""),
    ]

    def fake_cli(_argv, _env, cancel_check=None):
        return results.pop(0)

    with patch("executors.common.rq_job.validate_operation", return_value=write_op):
        with patch("executors.common.rq_job.command_argv", side_effect=lambda *_a, **_k: ["az"]):
            with patch("executors.common.rq_job.run_cli", side_effect=fake_cli):
                status, result, error = _run_step(
                    "azure", write_op, {}, lambda *_a: None, lambda: False
                )
    assert status == "succeeded"
    assert "verification" in result


@pytest.mark.unit
def test_run_azure_login_then_step():
    op = {
        "executable": "az",
        "args": ["account", "show"],
        "target": "identity",
        "preflight": [],
        "verify": [],
    }
    calls = []

    def fake_cli(argv, _env, cancel_check=None):
        calls.append(argv[1] if len(argv) > 1 else argv[0])
        if argv[:2] == ["az", "login"]:
            return CliResult(0, "", "")
        if argv[:3] == ["az", "account", "set"]:
            return CliResult(0, "", "")
        return CliResult(0, "{}", "")

    with patch("executors.common.rq_job.validate_operation", return_value=op):
        with patch("executors.common.rq_job.command_argv", return_value=["az", "account", "show"]):
            with patch("executors.common.rq_job.run_cli", side_effect=fake_cli):
                status, result, error = _run(
                    "azure",
                    op,
                    {"client_id": "c", "client_secret": "s", "tenant_id": "t", "subscription_id": "sub"},
                    {},
                    lambda *_a: None,
                    lambda: False,
                )
    assert status == "succeeded"
    assert "login" in calls


@pytest.mark.unit
def test_execute_provider_job_success_and_canceled_claim():
    payload = {
        "credentials": {"client_id": "c", "client_secret": "s", "tenant_id": "t"},
        "operation": {
            "executable": "az",
            "args": ["account", "show"],
            "target": "identity",
            "verify": [],
        },
    }
    with patch("executors.common.rq_job._claim", return_value=payload):
        with patch("executors.common.rq_job._post_event"):
            with patch("executors.common.rq_job._finish") as finish:
                with patch(
                    "executors.common.rq_job._run",
                    return_value=("succeeded", {"stdout": "{}"}, ""),
                ):
                    with patch("executors.common.rq_job._is_canceled", return_value=False):
                        result = execute_provider_job("a1", "azure")
    assert result["status"] == "succeeded"
    finish.assert_called_once()
    response = MagicMock()
    response.status_code = 409
    err = httpx.HTTPStatusError("conflict", request=MagicMock(), response=response)
    with patch("executors.common.rq_job._claim", side_effect=err):
        canceled = execute_provider_job("a1", "azure")
    assert canceled["status"] == "canceled"


@pytest.mark.unit
def test_finish_posts_result():
    client = MagicMock()
    client.__enter__.return_value = client
    client.__exit__.return_value = False
    response = MagicMock()
    response.raise_for_status.return_value = None
    client.post.return_value = response
    with patch("executors.common.rq_job.httpx.Client", return_value=client):
        _finish("a1", "succeeded", {"ok": True}, "")
    client.post.assert_called_once()
