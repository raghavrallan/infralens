"""Safe provider CLI subprocess runner used only inside executor images."""
import os
import re
import shutil
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Sequence

from app.execution.validation import PROVIDERS, validate_operation

MAX_OUTPUT = int(os.environ.get("EXECUTOR_MAX_OUTPUT", "200000"))
_SECRET_PATTERNS = (
    re.compile(r"(?i)(client[_ -]?secret|secret[_ -]?access[_ -]?key|access[_ -]?token|password|token)\s*[:=]\s*([^\s,]+)"),
    re.compile(r"(?i)(authorization\s*:\s*bearer\s+)([^\s]+)"),
    re.compile(r'(?i)(["\']?(?:clientSecret|accessToken|secretAccessKey|apiKey|token|password)["\']?\s*[:=]\s*["\']?)([^"\'\s,}]+)'),
)


@dataclass
class CliResult:
    returncode: int
    stdout: str
    stderr: str
    timed_out: bool = False
    canceled: bool = False


def redact(value: str) -> str:
    clean = value
    for pattern in _SECRET_PATTERNS:
        clean = pattern.sub(lambda match: f"{match.group(1)}[REDACTED]", clean)
    return clean[:MAX_OUTPUT]


def _resolve_argv(argv: Sequence[str]) -> list[str]:
    """Resolve provider launchers without falling back to shell execution.

    On Windows, Azure CLI is commonly installed as ``az.cmd``.  A ``.cmd``
    wrapper cannot be launched by ``subprocess`` with ``shell=False``.  The
    official installation also ships the embedded Python interpreter, so call
    Azure CLI's module directly instead of weakening the executor boundary.
    """
    executable = shutil.which(argv[0]) or argv[0]
    if os.name == "nt" and executable.lower().endswith((".cmd", ".bat")):
        if argv[0] == "az":
            wrapper = Path(executable)
            embedded_python = wrapper.parent.parent / "python.exe"
            if embedded_python.exists():
                return [str(embedded_python), "-IBm", "azure.cli", *argv[1:]]
        raise OSError(f"Provider CLI launcher is not directly executable: {executable}")
    return [executable, *argv[1:]]


def run_cli(
    argv: Sequence[str], env: Mapping[str, str], timeout: int | None = None,
    cancel_check: Callable[[], bool] | None = None,
) -> CliResult:
    """Run one already validated argv array with shell execution disabled."""
    allowed = set(PROVIDERS.values()) | {"terraform"}
    if not argv or argv[0] not in allowed:
        raise ValueError("Only provider CLI executables may be run")
    try:
        resolved_argv = _resolve_argv(argv)
    except OSError as exc:
        return CliResult(
            -1,
            "",
            f"Provider CLI unavailable in this executor: {argv[0]}. "
            f"Start the isolated {argv[0]} executor image with its CLI installed. ({exc})",
        )
    if cancel_check is None:
        try:
            completed = subprocess.run(
                resolved_argv, shell=False, capture_output=True, text=True,
                timeout=timeout or int(os.environ.get("EXECUTOR_TIMEOUT", "300")),
                env=dict(env), check=False,
            )
        except subprocess.TimeoutExpired as exc:
            return CliResult(-1, redact(str(exc.stdout or "")), redact(str(exc.stderr or "")), True)
        except OSError as exc:
            return CliResult(
                -1,
                "",
                f"Provider CLI unavailable in this executor: {argv[0]}. "
                f"Start the isolated {argv[0]} executor image with its CLI installed. ({exc})",
            )
        return CliResult(completed.returncode, redact(completed.stdout or ""), redact(completed.stderr or ""))
    try:
        process = subprocess.Popen(
            resolved_argv, shell=False, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, env=dict(env),
        )
        deadline = __import__("time").monotonic() + (timeout or int(os.environ.get("EXECUTOR_TIMEOUT", "300")))
        while True:
            try:
                stdout, stderr = process.communicate(timeout=0.5)
                return CliResult(process.returncode, redact(stdout or ""), redact(stderr or ""))
            except subprocess.TimeoutExpired:
                if cancel_check and cancel_check():
                    process.terminate()
                    try:
                        stdout, stderr = process.communicate(timeout=2)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        stdout, stderr = process.communicate()
                    return CliResult(-2, redact(stdout or ""), redact(stderr or ""), canceled=True)
                if __import__("time").monotonic() >= deadline:
                    process.kill()
                    stdout, stderr = process.communicate()
                    return CliResult(-1, redact(stdout or ""), redact(stderr or ""), timed_out=True)
    except OSError as exc:
        return CliResult(
            -1,
            "",
            f"Provider CLI unavailable in this executor: {argv[0]}. "
            f"Start the isolated {argv[0]} executor image with its CLI installed. ({exc})",
        )
