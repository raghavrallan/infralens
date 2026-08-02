"""RQ entrypoint for provider executor containers.

The Redis job contains only an action ID. The executor claims the action from
the API over private authenticated HTTP, receives credentials in memory, and
posts only redacted results back to the API.
"""
import os
import json
import shutil
import tempfile
from typing import Any

import httpx

from app.execution.validation import (
    command_argv,
    delete_verification_confirms_absence,
    validate_operation,
)
from executors.common.runner import CliResult, run_cli


def _headers() -> dict[str, str]:
    return {
        "X-Executor-Key": os.environ.get("EXECUTOR_SERVICE_KEY", "dev-executor-key"),
        "X-Executor-Provider": os.environ.get("EXECUTOR_PROVIDER", ""),
    }


def _control_url(path: str) -> str:
    return f"{os.environ.get('CONTROL_PLANE_URL', 'http://api:8000').rstrip('/')}{path}"


def _post_event(action_id: str, event_type: str, payload: dict[str, Any]) -> None:
    with httpx.Client(timeout=15) as client:
        response = client.post(_control_url(f"/internal/execution/jobs/{action_id}/events"), headers=_headers(), json={"type": event_type, "payload": payload})
        response.raise_for_status()


def _claim(action_id: str, provider: str) -> dict[str, Any]:
    with httpx.Client(timeout=15) as client:
        response = client.get(_control_url(f"/internal/execution/jobs/{action_id}/claim"), headers=_headers(), params={"provider": provider})
        response.raise_for_status()
        return response.json()


def _is_canceled(action_id: str, provider: str) -> bool:
    with httpx.Client(timeout=5) as client:
        response = client.get(_control_url(f"/internal/execution/jobs/{action_id}/canceled"), headers=_headers(), params={"provider": provider})
        response.raise_for_status()
        return bool(response.json().get("canceled"))


def _finish(action_id: str, status: str, result: dict[str, Any], error: str = "") -> None:
    with httpx.Client(timeout=15) as client:
        response = client.post(_control_url(f"/internal/execution/jobs/{action_id}/result"), headers=_headers(), json={"status": status, "result": result, "error": error})
        response.raise_for_status()


def _auth_env(provider: str, credentials: dict[str, Any], temp_dir: str) -> dict[str, str]:
    env = os.environ.copy()
    if provider == "azure":
        env["AZURE_CONFIG_DIR"] = temp_dir
    elif provider == "aws":
        env.update({
            "AWS_ACCESS_KEY_ID": str(credentials.get("access_key_id", "")),
            "AWS_SECRET_ACCESS_KEY": str(credentials.get("secret_access_key", "")),
            "AWS_DEFAULT_REGION": str(credentials.get("region", "us-east-1")),
        })
    elif provider == "github":
        env["GH_TOKEN"] = str(credentials.get("token", ""))
        if credentials.get("repo"):
            env["GH_REPO"] = str(credentials["repo"])
    elif provider == "terraform":
        # Terraform inherits cloud credentials from the linked Azure/AWS connection.
        cloud = str(credentials.get("cloud_provider") or "azure")
        if cloud == "aws":
            env.update({
                "AWS_ACCESS_KEY_ID": str(credentials.get("access_key_id", "")),
                "AWS_SECRET_ACCESS_KEY": str(credentials.get("secret_access_key", "")),
                "AWS_DEFAULT_REGION": str(credentials.get("region", "us-east-1")),
            })
        else:
            env["AZURE_CONFIG_DIR"] = temp_dir
            env["ARM_CLIENT_ID"] = str(credentials.get("client_id", ""))
            env["ARM_CLIENT_SECRET"] = str(credentials.get("client_secret", ""))
            env["ARM_TENANT_ID"] = str(credentials.get("tenant_id", ""))
            env["ARM_SUBSCRIPTION_ID"] = str(credentials.get("subscription_id", ""))
    return env


def _verification_succeeded(operation: dict[str, Any], verification: CliResult) -> bool:
    """Treat an absent target as success when verifying a completed delete."""
    if verification.returncode == 0:
        return True
    return delete_verification_confirms_absence(
        operation,
        verification.returncode,
        verification.stdout,
        verification.stderr,
        bool(getattr(verification, "timed_out", False)),
    )


def _preflight_found_existing(operation: dict[str, Any], preflight: CliResult) -> bool:
    """Recognize an existing target for an explicitly idempotent create step."""
    args = [str(item).lower() for item in operation.get("args", [])]
    known_idempotent_create = (
        operation.get("provider") == "azure"
        and (
            args[:2] == ["group", "create"]
            or args[:3] == ["network", "nsg", "create"]
        )
    )
    if not (operation.get("skip_if_exists") or known_idempotent_create) or not operation.get("preflight_expect"):
        return False
    expected = str(operation["preflight_expect"]).strip().lower()
    actual = _preflight_value(preflight.stdout)
    if expected == "false":
        return actual in {"true", "yes", "1"}
    if expected == "__absent__":
        return bool(actual and actual not in {"null", "none", "[]"})
    if expected == "0":
        try:
            return int(actual) > 0
        except ValueError:
            return False
    return False


def _preflight_value(stdout: str) -> str:
    """Normalize Azure CLI TSV/JSON empty and scalar responses."""
    text = str(stdout or "").strip()
    if not text:
        return ""
    try:
        parsed = json.loads(text)
    except (TypeError, ValueError):
        return text.lower()
    if parsed is None or parsed is False:
        return "false" if parsed is False else ""
    if parsed is True:
        return "true"
    if parsed == []:
        return ""
    if isinstance(parsed, list):
        return "\n".join(str(item).strip().lower() for item in parsed if str(item).strip())
    return str(parsed).strip().lower()


def _run_step(
    provider: str,
    operation: dict[str, Any],
    env: dict[str, str],
    emit: Any,
    cancel_check: Any,
) -> tuple[str, dict[str, Any], str]:
    scope = "write" if operation.get("verify") else "read_only"
    normalized = validate_operation(
        provider,
        str(operation["executable"]),
        list(operation["args"]),
        str(operation.get("target", "")),
        scope,
        list(operation.get("preflight", [])),
        list(operation.get("verify", [])),
    )
    if operation.get("preflight"):
        preflight = run_cli(command_argv(normalized, "preflight"), env, cancel_check=cancel_check)
        emit("preflight", preflight)
        if preflight.canceled:
            return "canceled", {}, "Canceled by user"
        if preflight.returncode:
            return "failed", {"preflight": {"stdout": preflight.stdout, "stderr": preflight.stderr}}, "Preflight command failed"
        expected = str(operation.get("preflight_expect") or "").strip().lower()
        actual = _preflight_value(preflight.stdout)
        args = [str(item).lower() for item in operation.get("args", [])]
        legacy_empty_parent = (
            expected == "false"
            and not actual
            and operation.get("skip_if_exists")
            and args[:2] == ["group", "create"]
        )
        absent_check_passed = (
            expected == "__absent__" and actual in {"", "null", "none", "[]"}
        ) or legacy_empty_parent
        if expected and not absent_check_passed and actual != expected:
            if _preflight_found_existing(operation, preflight):
                verification = run_cli(command_argv(normalized, "verify"), env, cancel_check=cancel_check)
                emit("verify", verification)
                if verification.canceled:
                    return "canceled", {}, "Canceled by user"
                if verification.timed_out or verification.returncode:
                    return "failed", {"verification": {"stdout": verification.stdout, "stderr": verification.stderr}}, "Existing resource verification failed"
                emit("step_skipped", CliResult(0, "create skipped; resource already exists", ""))
                return "succeeded", {
                    "skipped": True,
                    "verification": {
                        "returncode": verification.returncode,
                        "stdout": verification.stdout,
                        "stderr": verification.stderr,
                        "timed_out": verification.timed_out,
                    },
                }, ""
            return (
                "failed",
                {"preflight": {"stdout": preflight.stdout, "stderr": preflight.stderr}},
                f"Preflight state does not permit this action "
                f"(expected {expected!r}, received {actual or '<empty>'!r})",
            )

    execution = run_cli(command_argv(normalized), env, cancel_check=cancel_check)
    emit("execute", execution)
    if execution.canceled:
        return "canceled", {"stdout": execution.stdout, "stderr": execution.stderr}, "Canceled by user"
    result: dict[str, Any] = {"returncode": execution.returncode, "stdout": execution.stdout, "stderr": execution.stderr}
    if execution.timed_out:
        return "failed", result, "Provider CLI command timed out"
    if execution.returncode:
        return "failed", result, "Provider CLI command failed"

    if operation.get("verify"):
        verification = run_cli(command_argv(normalized, "verify"), env, cancel_check=cancel_check)
        emit("verify", verification)
        if verification.canceled:
            return "canceled", result, "Canceled by user"
        result["verification"] = {
            "returncode": verification.returncode,
            "stdout": verification.stdout,
            "stderr": verification.stderr,
            "timed_out": verification.timed_out,
        }
        if verification.timed_out or (
            verification.returncode and not _verification_succeeded(operation, verification)
        ):
            return "verification_failed", result, "Post-write verification failed"
    return "succeeded", result, ""


def _run(
    provider: str,
    operation: dict[str, Any],
    credentials: dict[str, Any],
    env: dict[str, str],
    emit: Any,
    cancel_check: Any,
) -> tuple[str, dict[str, Any], str]:
    steps = operation.get("steps") if isinstance(operation.get("steps"), list) else []
    operations = [step for step in steps if isinstance(step, dict)] or [operation]
    # Validate every step before authenticating or changing the provider.
    for step in operations:
        validate_operation(
            provider,
            str(step["executable"]),
            list(step["args"]),
            str(step.get("target", "")),
            "write" if step.get("verify") else "read_only",
            list(step.get("preflight", [])),
            list(step.get("verify", [])),
        )

    if provider == "azure" or (
        provider == "terraform"
        and str(credentials.get("cloud_provider") or "azure") == "azure"
        and credentials.get("client_id")
    ):
        login = run_cli(["az", "login", "--service-principal", "--username", str(credentials.get("client_id", "")), "--password", str(credentials.get("client_secret", "")), "--tenant", str(credentials.get("tenant_id", "")), "--output", "none"], env, cancel_check=cancel_check)
        emit("azure_login", login)
        if login.canceled:
            return "canceled", {}, "Canceled by user"
        if login.returncode:
            return "failed", {"stdout": login.stdout, "stderr": login.stderr}, "Azure CLI login failed"
        subscription = str(credentials.get("subscription_id", ""))
        if subscription:
            selected = run_cli(["az", "account", "set", "--subscription", subscription], env, cancel_check=cancel_check)
            emit("azure_subscription", selected)
            if selected.canceled:
                return "canceled", {}, "Canceled by user"
            if selected.returncode:
                return "failed", {"stdout": selected.stdout, "stderr": selected.stderr}, "Azure subscription selection failed"

    results: list[dict[str, Any]] = []
    for index, step in enumerate(operations, 1):
        emit("step_started", CliResult(0, f"step={index}", "", False, False))
        status, result, error = _run_step(provider, step, env, emit, cancel_check)
        results.append({"step": index, "status": status, **result})
        if status != "succeeded":
            return status, {"steps": results}, error
    return "succeeded", {"steps": results}, ""


def execute_provider_job(action_id: str, provider: str) -> dict[str, Any]:
    try:
        payload = _claim(action_id, provider)
    except httpx.HTTPStatusError as exc:
        # A queued job can remain in Redis after the user stops it. Treat the
        # control-plane 409 as a normal cancellation, not an executor failure.
        if exc.response.status_code == 409:
            return {"action_id": action_id, "status": "canceled"}
        raise
    credentials = dict(payload.get("credentials") or {})
    temp_dir = tempfile.mkdtemp(prefix=f"devsecops-{provider}-")
    try:
        _post_event(action_id, "action_output", {"phase": "started", "provider": provider})
        def emit(phase: str, cli_result: CliResult) -> None:
            _post_event(action_id, "action_output", {"phase": phase, "returncode": cli_result.returncode, "stdout": cli_result.stdout, "stderr": cli_result.stderr, "timed_out": cli_result.timed_out, "canceled": cli_result.canceled})
        status, result, error = _run(provider, dict(payload["operation"]), credentials, _auth_env(provider, credentials, temp_dir), emit, lambda: _is_canceled(action_id, provider))
        _post_event(action_id, "action_verified" if status == "succeeded" and payload["operation"].get("verify") else "action_output", {"phase": "completed", "status": status})
        _finish(action_id, status, result, error)
        return {"action_id": action_id, "status": status}
    except Exception as exc:  # noqa: BLE001 - report failure to the control plane
        try:
            _finish(action_id, "failed", {}, str(exc))
        finally:
            raise
    finally:
        credentials.clear()
        shutil.rmtree(temp_dir, ignore_errors=True)
