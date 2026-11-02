"""Feature flags for agent runtime integrations (env-driven, safe defaults)."""
from __future__ import annotations

import os
from functools import lru_cache
from typing import TypedDict


def _truthy(value: str | None, default: bool = False) -> bool:
    if value is None or value.strip() == "":
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


class FeatureFlags(TypedDict):
    architect_langgraph: bool
    n8n_webhooks: bool
    debug_react: bool
    chat_langgraph: bool


@lru_cache(maxsize=1)
def get_feature_flags() -> FeatureFlags:
    """Cached flag snapshot. Restart the process after changing env vars."""
    return {
        # Off by default until Phase 1 parity is validated in staging.
        "architect_langgraph": _truthy(os.environ.get("ARCHITECT_LANGGRAPH"), False),
        "n8n_webhooks": _truthy(os.environ.get("N8N_WEBHOOKS_ENABLED"), False),
        "debug_react": _truthy(os.environ.get("DEBUG_REACT_ENABLED"), False),
        "chat_langgraph": _truthy(os.environ.get("CHAT_LANGGRAPH"), False),
    }


def feature_enabled(name: str) -> bool:
    flags = get_feature_flags()
    return bool(flags.get(name))  # type: ignore[arg-type]


def clear_flag_cache() -> None:
    get_feature_flags.cache_clear()
