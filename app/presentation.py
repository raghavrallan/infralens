"""Display-only branding transforms for the EQIP → MetLife alias.

Stored data, Azure resource IDs used by tools, and DB rows stay as EQIP / eq-*.
Only outbound API / SSE payloads are rewritten for the UI:

- Project / product name: EQIP → MetLife (any casing)
- Resource-style tokens: eq- → ml-, eq_ → ml_, -eq- → -ml-, etc.

Reverse mapping is available so user/UI text that says MetLife / ml- can be
translated back before tool calls when needed.
"""
from __future__ import annotations

import re
from typing import Any

# Whole-word product name (EQIP / eqip / Eqip → MetLife / metlife / Metlife)
_EQIP_WORD = re.compile(r"\beqip\b", re.IGNORECASE)

# Resource segments: leading eq-, eq_, or eq as a hyphen/underscore delimited token.
# Avoids mangling English words like "request", "equal", "sequence".
_EQ_RESOURCE = re.compile(
    r"(?i)(?<![A-Za-z0-9])eq(?=[-_])|(?<=[-_])eq(?=[-_]|$)|(?<![A-Za-z0-9])eq(?=\d)"
)

# Reverse: MetLife product name and ml- resource tokens
_METLIFE_WORD = re.compile(r"\bmetlife\b", re.IGNORECASE)
_ML_RESOURCE = re.compile(
    r"(?i)(?<![A-Za-z0-9])ml(?=[-_])|(?<=[-_])ml(?=[-_]|$)|(?<![A-Za-z0-9])ml(?=\d)"
)


def display_text(value: str) -> str:
    """Rewrite EQIP / eq-* tokens for UI display."""
    if not value or not isinstance(value, str):
        return value

    # Product name always brands as MetLife (never METLIFE / metlife variants).
    text = _EQIP_WORD.sub("MetLife", value)

    def eq_res_sub(match: re.Match[str]) -> str:
        token = match.group(0)
        if token.isupper():
            return "ML"
        if token[:1].isupper():
            return "Ml"
        return "ml"

    text = _EQ_RESOURCE.sub(eq_res_sub, text)
    return text


def internal_text(value: str) -> str:
    """Reverse UI branding so tool calls can use real EQIP / eq-* names."""
    if not value or not isinstance(value, str):
        return value

    # Accept any MetLife casing back to EQIP for tools / Azure lookups.
    text = _METLIFE_WORD.sub("EQIP", value)

    def ml_res_sub(match: re.Match[str]) -> str:
        token = match.group(0)
        if token.isupper():
            return "EQ"
        if token[:1].isupper():
            return "Eq"
        return "eq"

    text = _ML_RESOURCE.sub(ml_res_sub, text)
    return text


def display_value(value: Any) -> Any:
    """Recursively apply display_text to strings inside dicts/lists."""
    if isinstance(value, str):
        return display_text(value)
    if isinstance(value, list):
        return [display_value(item) for item in value]
    if isinstance(value, tuple):
        return tuple(display_value(item) for item in value)
    if isinstance(value, dict):
        # Keep ids and technical keys intact when they look like UUIDs / opaque ids,
        # but still brand human-facing string fields.
        skip_keys = {
            "id",
            "chat_id",
            "project_id",
            "run_id",
            "workflow_id",
            "message_id",
            "edit_message_id",
            "action_id",
            "approver",
            "status",
            "type",
            "trigger",
            "method",
            "skill",
            "module",
            "gate_decision",
            "risk_class",
            "blast_radius",
            "created_at",
            "updated_at",
            "started_at",
            "finished_at",
            "expires_at",
        }
        out: dict[str, Any] = {}
        for key, item in value.items():
            if key in skip_keys and isinstance(item, str):
                out[key] = item
            else:
                out[key] = display_value(item)
        return out
    return value
