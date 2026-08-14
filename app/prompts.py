"""Langfuse Prompt Management with in-code fallbacks.

Prompts are fetched by name (production label). If Langfuse is unreachable or
the prompt is missing, the hardcoded fallback is used so the app keeps working.
"""
from __future__ import annotations

import logging
import re
from typing import Any, Optional

from app import observability

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


def get_text_prompt(
    name: str,
    *,
    fallback: str,
    variables: Optional[dict[str, Any]] = None,
    label: str = "production",
) -> str:
    """Return a compiled text prompt from Langfuse, or the local fallback."""
    if not observability.tracing_enabled():
        return _fallback_compile(fallback, variables)
    try:
        from langfuse import get_client

        prompt = get_client().get_prompt(name, label=label)
        observability.set_active_prompt(prompt)
        compiled = prompt.compile(**(variables or {}))
        return compiled if isinstance(compiled, str) else str(compiled)
    except Exception as exc:  # noqa: BLE001 — always degrade gracefully
        logger.debug("Langfuse prompt %s unavailable (%s); using fallback", name, exc)
        return _fallback_compile(fallback, variables)


def ensure_text_prompt(
    name: str,
    prompt: str,
    *,
    label: str = "production",
) -> None:
    """Create the prompt in Langfuse when it does not already exist."""
    if not observability.tracing_enabled():
        return
    try:
        from langfuse import get_client

        client = get_client()
        try:
            client.get_prompt(name, label=label)
            return
        except Exception:
            client.create_prompt(
                name=name,
                type="text",
                prompt=prompt,
                labels=[label],
            )
    except Exception as exc:  # noqa: BLE001
        logger.warning("Could not ensure Langfuse prompt %s: %s", name, exc)


def seed_core_prompts() -> None:
    """Push core + skill system prompts into Langfuse (idempotent)."""
    if not observability.tracing_enabled():
        return

    from app.chat_memory import MEMORY_SYSTEM_PROMPT
    from app.intelligence.findings import EXTRACT_SYSTEM_PROMPT_FALLBACK
    from app.orchestrator import (
        DETAILED_PLAN_SYSTEM_PROMPT_TEMPLATE,
        ORCHESTRATOR_SYSTEM_PROMPT,
        PLANNER_SYSTEM_PROMPT_TEMPLATE,
    )
    from app.skills import registry

    ensure_text_prompt("orchestrator-system", ORCHESTRATOR_SYSTEM_PROMPT)
    ensure_text_prompt("planner-system", PLANNER_SYSTEM_PROMPT_TEMPLATE)
    ensure_text_prompt("detailed-plan-system", DETAILED_PLAN_SYSTEM_PROMPT_TEMPLATE)
    ensure_text_prompt("chat-memory-system", MEMORY_SYSTEM_PROMPT)
    ensure_text_prompt("finding-extract-system", EXTRACT_SYSTEM_PROMPT_FALLBACK)

    for skill in registry.all():
        if skill.system_prompt:
            ensure_text_prompt(f"skill-{skill.name}", skill.system_prompt)
    try:
        from app.agents.solution_architect.prompts import seed_architect_prompts

        seed_architect_prompts()
    except Exception:
        pass
