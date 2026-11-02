"""Validation for provider CLI operations.

The API accepts structured argument arrays and never accepts a shell command.
This module is intentionally independent of the provider SDKs and executors so
the same policy can be tested before an action is persisted or dispatched.
"""
import hashlib
import json
import re
import shlex
from typing import Any

PROVIDERS = {"azure": "az", "aws": "aws", "github": "gh", "terraform": "terraform"}
# Write phases that must carry a machine-executable rollback operation.
_TF_WRITE_PHASES = {"apply", "destroy"}
_SHELL_MARKERS = re.compile(r"[\x00\r\n|;&><$()`\\]")
_DANGEROUS_EXECUTABLES = {"sh", "bash", "cmd", "cmd.exe", "powershell", "pwsh"}
_SECRET_FLAGS = {"--password", "--client-secret", "--secret", "--token", "--access-key", "--secret-key"}
_SECRET_FLAG_PATTERN = re.compile(r"^--?(?:client[-_])?(?:secret|secret[-_]key|token|access[-_]token|password|access[-_]key|api[-_]key|api[-_]token)(?:=|$)", re.IGNORECASE)
_QUERY_FLAGS = {"--query", "--jq"}
MAX_ARGS = 128
MAX_ARG_LENGTH = 2048


def _check_args(args: list[str], label: str) -> list[str]:
    if not isinstance(args, list) or not args:
        raise ValueError(f"{label} must contain at least one CLI argument")
    if len(args) > MAX_ARGS:
        raise ValueError(f"{label} contains too many arguments")
    clean: list[str] = []
    for index, arg in enumerate(args):
        if not isinstance(arg, str) or not arg or len(arg) > MAX_ARG_LENGTH:
            raise ValueError(f"{label} contains an invalid argument")
        # A sentence-ending semicolon is common when a user pastes a CLI
        # request into chat. It is not shell syntax when argv is passed with
        # shell=False, so remove only that final punctuation before validation.
        if arg.endswith(";") and not arg.endswith(";;"):
            arg = arg[:-1]
            if not arg:
                raise ValueError(f"{label} contains an invalid argument")
        query_expression = (
            index > 0
            and isinstance(args[index - 1], str)
            and args[index - 1] in _QUERY_FLAGS
        )
        # Provider query languages legitimately use `|` (for example Azure
        # JMESPath: `[?name=='nsg'] | length(@)`). The executor receives an
        # argv list with shell=False, so this is data syntax, not a shell pipe.
        # Keep rejecting every other shell marker, and reject pipes everywhere
        # except the value immediately following a supported query flag.
        shell_match = _SHELL_MARKERS.search(arg)
        if shell_match and not (
            query_expression
            and shell_match.group(0) == "|"
            and not re.search(r"[\x00\r\n;&><$`\\]", arg)
        ):
            raise ValueError("Shell syntax is not allowed in provider arguments")
        if arg.lower() in _DANGEROUS_EXECUTABLES:
            raise ValueError("Nested shell execution is not allowed")
        if arg.lower() in _SECRET_FLAGS or _SECRET_FLAG_PATTERN.search(arg):
            raise ValueError("Credentials must come from the stored provider connection")
        clean.append(arg)
    return clean


def validate_rollback_plan(
    rollback: str,
    *,
    provider: str,
    args: list[str],
    rollback_operation: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Require a machine-executable rollback for write actions.

    Accepts either a structured ``rollback_operation`` (preferred) or a JSON
    object embedded in the rollback text. Plain prose alone is rejected.
    """
    if rollback_operation and isinstance(rollback_operation, dict):
        op = rollback_operation
    else:
        text = str(rollback or "").strip()
        if not text:
            raise ValueError("Write actions require a rollback plan")
        try:
            parsed = json.loads(text)
        except (TypeError, json.JSONDecodeError):
            # Allow a concise prose plan only when it clearly names an undo command
            # for non-terraform providers (legacy chat path). Prefer structured ops.
            lowered = text.lower()
            has_undo = any(
                marker in lowered
                for marker in ("delete", "remove", "destroy", "rollback", "revert", "undo", "az ", "aws ", "gh ", "terraform ")
            )
            if not has_undo or len(text) < 12:
                raise ValueError(
                    "Write actions require a machine-executable rollback plan "
                    "(structured rollback_operation or JSON undo command)"
                ) from None
            return {"mode": "prose", "summary": text[:1000]}
        if not isinstance(parsed, dict):
            raise ValueError("Rollback JSON must be an object describing the undo operation")
        op = parsed

    rb_provider = str(op.get("provider") or provider)
    rb_executable = str(op.get("executable") or PROVIDERS.get(rb_provider, ""))
    rb_args = [str(item) for item in op.get("args", [])]
    if rb_provider not in PROVIDERS:
        raise ValueError("Rollback operation uses an unsupported provider")
    if rb_executable != PROVIDERS[rb_provider]:
        raise ValueError("Rollback executable does not match provider")
    if not rb_args:
        raise ValueError("Rollback operation requires args")
    _check_args(rb_args, "rollback.args")
    return {
        "mode": "structured",
        "provider": rb_provider,
        "executable": rb_executable,
        "args": rb_args,
        "target": str(op.get("target") or "")[:400],
        "summary": str(op.get("expected_result") or op.get("risk") or rollback or "")[:1000],
    }


def validate_operation(
    provider: str,
    executable: str,
    args: list[str],
    target: str,
    access_scope: str,
    preflight: list[str] | None = None,
    verify: list[str] | None = None,
) -> dict[str, Any]:
    """Validate and normalize a provider operation for persistence."""
    expected = PROVIDERS.get(provider)
    if expected is None:
        raise ValueError("Unsupported provider")
    if executable != expected:
        raise ValueError(f"Provider {provider} must use the {expected} executable")
    if access_scope not in {"read_only", "write"}:
        raise ValueError("Unsupported access scope")
    if not isinstance(target, str) or len(target) > 400 or _SHELL_MARKERS.search(target):
        raise ValueError("Invalid action target")
    normalized = {
        "provider": provider,
        "executable": executable,
        "args": _check_args(args, "args"),
        "target": target,
        "preflight": _check_args(preflight, "preflight") if preflight else [],
        "verify": _check_args(verify, "verify") if verify else [],
    }
    if access_scope == "write" and (not normalized["preflight"] or not normalized["verify"]):
        raise ValueError("Write actions require both a read-before-write preflight and verification command")
    if provider == "terraform" and access_scope == "write":
        phase = (normalized["args"][0] if normalized["args"] else "").lower()
        if phase not in _TF_WRITE_PHASES and "apply" not in normalized["args"] and "destroy" not in normalized["args"]:
            raise ValueError("Terraform write actions must be apply or destroy")
    return normalized


def command_argv(operation: dict[str, Any], phase: str = "execute") -> list[str]:
    executable = str(operation["executable"])
    args = operation.get(phase if phase in {"preflight", "verify"} else "args", [])
    return [executable, *args]


def command_preview(operation: dict[str, Any]) -> str:
    return shlex.join(command_argv(operation))


def delete_verification_confirms_absence(
    operation: dict[str, Any], returncode: int, stdout: str = "", stderr: str = "",
    timed_out: bool = False,
) -> bool:
    """Recognize a provider's expected not-found response after deletion."""
    if timed_out or not returncode:
        return False
    args = [str(item).lower() for item in operation.get("args", [])]
    verify_args = [str(item).lower() for item in operation.get("verify", [])]
    is_delete = any(item in {"delete", "remove", "destroy"} for item in args)
    is_lookup = any(item in {"show", "get", "describe", "exists"} for item in verify_args)
    if not (is_delete and is_lookup):
        return False
    output = f"{stdout}\n{stderr}".lower()
    return any(
        marker in output
        for marker in (
            "resourcegroupnotfound",
            "could not be found",
            "not found",
            "does not exist",
            "notfound",
        )
    )


def operation_hash(operation: dict[str, Any], access_scope: str) -> str:
    canonical = json.dumps(
        {"operation": operation, "access_scope": access_scope},
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()
