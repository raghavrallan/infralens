"""Display-only branding transforms for the EQIP → mlife alias.

Stored data, Azure resource IDs used by tools, and DB rows stay as EQIP / eq-*.
Only outbound API / SSE payloads are rewritten for the UI:

- Product / path tokens: EQIP, eqip, eqip_backend, eqip-frontend → mlife*
- Resource-style tokens: eq- → ml-, eq_ → ml_, -eq- → -ml-, etc.

Reverse mapping is available so user/UI text that says mlife / ml- can be
translated back before tool calls when needed.
"""
from __future__ import annotations

import re
from typing import Any

# "eqip" as a standalone word OR as the start of a compound path/id
# (eqip_backend, eqip-frontend, eqip/Dockerfile). Underscore is a word char,
# so \\beqip\\b alone misses those compounds.
_EQIP_TOKEN = re.compile(r"(?i)(?<![A-Za-z0-9])eqip(?![A-Za-z])")

# Resource segments: leading eq-, eq_, or eq as a hyphen/underscore delimited token.
# Avoids mangling English words like "request", "equal", "sequence".
_EQ_RESOURCE = re.compile(
    r"(?i)(?<![A-Za-z0-9])eq(?=[-_])|(?<=[-_])eq(?=[-_]|$)|(?<![A-Za-z0-9])eq(?=\d)"
)

# Reverse: mlife compounds first, then standalone product name → EQIP
_MLIFE_PREFIX = re.compile(
    r"(?i)(?<![A-Za-z0-9])(?:mlife|metlife)(?=[_\-/.\\])"
)
_MLIFE_WORD = re.compile(r"(?i)\b(?:mlife|metlife)\b")
_ML_RESOURCE = re.compile(
    r"(?i)(?<![A-Za-z0-9])ml(?=[-_])|(?<=[-_])ml(?=[-_]|$)|(?<![A-Za-z0-9])ml(?=\d)"
)


def display_text(value: str) -> str:
    """Rewrite EQIP / eqip* / eq-* tokens for UI display."""
    if not value or not isinstance(value, str):
        return value

    # Product name and path prefixes always brand as mlife.
    text = _EQIP_TOKEN.sub("mlife", value)

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

    # Compounds like mlife_backend → eqip_backend (keep path casing).
    text = _MLIFE_PREFIX.sub("eqip", value)
    # Standalone product name back to EQIP for tools / Azure lookups.
    text = _MLIFE_WORD.sub("EQIP", text)

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
