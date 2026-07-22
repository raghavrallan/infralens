"""Small control-plane client for CLI-backed read evidence.

This is deliberately opt-in. Until each provider report has CLI parity, the
orchestrator can fall back to its existing read implementation when an
executor is unavailable or returns an incomplete result.
"""
import json
import time
from typing import Any

from app.execution import service

_READ_COMMANDS = {
    "azure": ("az", ["account", "show", "--output", "json"]),
    "aws": ("aws", ["sts", "get-caller-identity", "--output", "json"]),
    "github": ("gh", ["api", "user"]),
}


def read_environment(project_id: str, provider: str, timeout: float = 20.0) -> str:
    executable, args = _READ_COMMANDS[provider]
    action = service.create_action(
        project_id=project_id,
        provider=provider,
        executable=executable,
        args=args,
        target="connected account",
        access_scope="read_only",
        expected_result="JSON identity and connection evidence",
        risk="Read-only identity query",
        rollback="Not applicable",
        preflight=[],
        verify=[],
        requested_by="orchestrator",
    )
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        current = service.get_action(action["id"])
        if current["status"] in {"succeeded", "failed", "verification_failed"}:
            if current["status"] != "succeeded":
                raise RuntimeError(current.get("error") or "CLI read failed")
            result: dict[str, Any] = current.get("result") or {}
            stdout = result.get("stdout", "")
            if not stdout:
                raise RuntimeError("CLI read returned no evidence")
            try:
                return json.dumps(json.loads(stdout), indent=2, sort_keys=True)
            except (TypeError, json.JSONDecodeError):
                return str(stdout)
        time.sleep(0.25)
    raise TimeoutError(f"Timed out waiting for {provider} read executor")

