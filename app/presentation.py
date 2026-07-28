"""Display-only branding transforms for the EQIP → mlife alias.

Stored data, Azure resource IDs used by tools, and DB rows stay as EQIP / eq-*.
Only outbound API / SSE payloads are rewritten for the UI:

- Product / path tokens: EQIP, eqip, eqip_backend → mlife*
- Resource tokens: eq-foo, eq_foo, eq123 → ml*
- Glued org prefixes: eqacrregistry…, eqdevstorage… → ml*

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

# Common English words that start with "eq" — do not brand these.
_EQ_ENGLISH = (
    r"(?:ual(?:ly|s|ity|ize|ised|ized)?|uation(?:s)?|uip(?:ment|ped|ping)?|"
    r"uity|uivalent(?:ly)?|uator|uilibrium|uine|uate(?:d|s|ing)?|"
    r"uidistant|uilateral|uanimous(?:ly)?)"
)

# Glued org prefix in Azure resource names: eqacrregistry…, eqdevstorage…,
# eqcommonstorage — "eq" followed by more letters, excluding English words.
_EQ_GLUED = re.compile(
    rf"(?i)(?<![A-Za-z0-9])eq(?!{_EQ_ENGLISH}\b)(?=[a-z]{{2,}})"
)

# Resource segments: leading eq-, eq_, or eq as a hyphen/underscore delimited token.
_EQ_RESOURCE = re.compile(
    r"(?i)(?<![A-Za-z0-9])eq(?=[-_])|(?<=[-_])eq(?=[-_]|$)|(?<![A-Za-z0-9])eq(?=\d)"
)

# Reverse: mlife compounds first, then glued ml* resource ids, then ml-/ml_
_MLIFE_PREFIX = re.compile(
    r"(?i)(?<![A-Za-z0-9])(?:mlife|metlife)(?=[_\-/.\\])"
)
_MLIFE_WORD = re.compile(r"(?i)\b(?:mlife|metlife)\b")
# Avoid turning "mlife…" into "eqife…"; only glued Azure-style prefixes.
_ML_GLUED = re.compile(
    r"(?i)(?<![A-Za-z0-9])ml(?!ife\b|ife(?=[_\-/.\\A-Z]))(?=[a-z]{2,})"
)
_ML_RESOURCE = re.compile(
    r"(?i)(?<![A-Za-z0-9])ml(?=[-_])|(?<=[-_])ml(?=[-_]|$)|(?<![A-Za-z0-9])ml(?=\d)"
)


def _brand_eq_token(match: re.Match[str]) -> str:
    token = match.group(0)
    if token.isupper():
        return "ML"
    if token[:1].isupper():
        return "Ml"
    return "ml"


def _brand_ml_token(match: re.Match[str]) -> str:
    token = match.group(0)
    if token.isupper():
        return "EQ"
    if token[:1].isupper():
        return "Eq"
    return "eq"


def display_text(value: str) -> str:
    """Rewrite EQIP / eqip* / eq* / eq-* tokens for UI display."""
    if not value or not isinstance(value, str):
        return value

    # Order matters: eqip → mlife before bare "eq" rewrites.
    text = _EQIP_TOKEN.sub("mlife", value)
    text = _EQ_GLUED.sub(_brand_eq_token, text)
    text = _EQ_RESOURCE.sub(_brand_eq_token, text)
    return text


def internal_text(value: str) -> str:
    """Reverse UI branding so tool calls can use real EQIP / eq-* names."""
    if not value or not isinstance(value, str):
        return value

    # Compounds like mlife_backend → eqip_backend (keep path casing).
    text = _MLIFE_PREFIX.sub("eqip", value)
    # Standalone product name back to EQIP for tools / Azure lookups.
    text = _MLIFE_WORD.sub("EQIP", text)
    text = _ML_GLUED.sub(_brand_ml_token, text)
    text = _ML_RESOURCE.sub(_brand_ml_token, text)
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
