"""Langfuse Prompt Management with in-code fallbacks.

Prompts are fetched by name (production label). If Langfuse is unreachable or
the prompt is missing, the hardcoded fallback is used so the app keeps working.
"""
from __future__ import annotations

import logging
import re
from typing import Any, Optional

from app.core import observability

logger = logging.getLogger(__name__)

_VAR_RE = re.compile(r"\{\{\s*([a-zA-Z_][a-zA-Z0-9_]*)\s*\}\}")


def _fallback_compile(template: str, variables: Optional[dict[str, Any]]) -> str:
    if not variables:
        return template

    def repl(match: re.Match[str]) -> str:
        key = match.group(1)
        if key not in variables:
            return match.group(0)
        return str(variables[key])

    return _VAR_RE.sub(repl, template)


def _handle_langfuse_failure(name: str, exc: BaseException, *, action: str) -> None:
    if observability.is_transport_error(exc):
        observability.mark_langfuse_unreachable(str(exc) or exc.__class__.__name__)
        logger.warning(
            "Langfuse %s for %s failed (%s); using local prompts for this process",
            action,
            name,
            exc,
        )
    else:
        logger.debug("Langfuse %s for %s unavailable (%s)", action, name, exc)


def get_text_prompt(
    name: str,
    *,
    fallback: str,
    variables: Optional[dict[str, Any]] = None,
    label: str = "production",
) -> str:
    """Return a compiled text prompt from Langfuse, or the local fallback."""
    if not observability.tracing_enabled() or observability.langfuse_unreachable():
        return _fallback_compile(fallback, variables)
    try:
        client = observability.get_langfuse_client()
        prompt = client.get_prompt(
            name,
            label=label,
            max_retries=0,
            fetch_timeout_seconds=observability.prompt_fetch_timeout_seconds(),
        )
        observability.set_active_prompt(prompt)
        compiled = prompt.compile(**(variables or {}))
        return compiled if isinstance(compiled, str) else str(compiled)
    except Exception as exc:  # noqa: BLE001 — always degrade gracefully
        _handle_langfuse_failure(name, exc, action="fetch")
        return _fallback_compile(fallback, variables)


def ensure_text_prompt(
    name: str,
    prompt: str,
    *,
    label: str = "production",
) -> None:
    """Create the prompt in Langfuse when it does not already exist."""
    if not observability.tracing_enabled() or observability.langfuse_unreachable():
        return
    try:
        client = observability.get_langfuse_client()
        try:
            client.get_prompt(
                name,
                label=label,
                max_retries=0,
                fetch_timeout_seconds=observability.prompt_fetch_timeout_seconds(),
            )
            return
        except Exception:
            client.create_prompt(
                name=name,
                type="text",
                prompt=prompt,
                labels=[label],
            )
    except Exception as exc:  # noqa: BLE001
        _handle_langfuse_failure(name, exc, action="ensure")


def seed_core_prompts() -> None:
    """Push core + skill system prompts into Langfuse (idempotent).

    Skips entirely when Langfuse is disabled or the host fails a short probe so
    API startup is never blocked on an unreachable aigovernance/Langfuse host.
    """
    if not observability.tracing_enabled():
        return
    if observability.langfuse_unreachable():
        return
    if not observability.probe_langfuse():
        return

    from app.chat.chat_memory import MEMORY_SYSTEM_PROMPT
    from app.intelligence.findings import EXTRACT_SYSTEM_PROMPT_FALLBACK
    from app.chat.orchestrator import (
        DETAILED_PLAN_SYSTEM_PROMPT_TEMPLATE,
        ORCHESTRATOR_SYSTEM_PROMPT,
        PLANNER_SYSTEM_PROMPT_TEMPLATE,
    )
    from app.skills import registry

    ensure_text_prompt("orchestrator-system", ORCHESTRATOR_SYSTEM_PROMPT)
    if observability.langfuse_unreachable():
        return
    ensure_text_prompt("planner-system", PLANNER_SYSTEM_PROMPT_TEMPLATE)
    ensure_text_prompt("detailed-plan-system", DETAILED_PLAN_SYSTEM_PROMPT_TEMPLATE)
    ensure_text_prompt("chat-memory-system", MEMORY_SYSTEM_PROMPT)
    ensure_text_prompt("finding-extract-system", EXTRACT_SYSTEM_PROMPT_FALLBACK)

    for skill in registry.all():
        if observability.langfuse_unreachable():
            return
        if skill.system_prompt:
            ensure_text_prompt(f"skill-{skill.name}", skill.system_prompt)
    try:
        from app.agents.solution_architect.prompts import seed_architect_prompts

        if not observability.langfuse_unreachable():
            seed_architect_prompts()
    except Exception:
        pass
