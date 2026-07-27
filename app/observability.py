"""Langfuse tracing context: session, user, tags, and feature labels.

Chat turns use chat_id as session_id so Langfuse Sessions group a conversation.
Authenticated username/id is attached as user_id for per-user cost and quality.
"""
from __future__ import annotations

import os
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any, Iterator, Optional

_session_id: ContextVar[Optional[str]] = ContextVar("langfuse_session_id", default=None)
_user_id: ContextVar[Optional[str]] = ContextVar("langfuse_user_id", default=None)
_tags: ContextVar[tuple[str, ...]] = ContextVar("langfuse_tags", default=())
_feature: ContextVar[Optional[str]] = ContextVar("langfuse_feature", default=None)
_generation_name: ContextVar[Optional[str]] = ContextVar(
    "langfuse_generation_name", default=None
)
# Most recently fetched Langfuse prompt object (linked on the next generation).
_active_prompt: ContextVar[Any] = ContextVar("langfuse_active_prompt", default=None)


def tracing_enabled() -> bool:
    if os.environ.get("LANGFUSE_TRACING_ENABLED", "true").lower() in {
        "0",
        "false",
        "no",
        "off",
    }:
        return False
    return bool(
        os.environ.get("LANGFUSE_PUBLIC_KEY") and os.environ.get("LANGFUSE_SECRET_KEY")
    )


def ensure_host_alias() -> None:
    """Langfuse accepts BASE_URL; some SDK paths still read HOST."""
    base = os.environ.get("LANGFUSE_BASE_URL") or os.environ.get("LANGFUSE_HOST")
    if base:
        os.environ.setdefault("LANGFUSE_BASE_URL", base)
        os.environ.setdefault("LANGFUSE_HOST", base)


@contextmanager
def tracing_context(
    *,
    session_id: Optional[str] = None,
    user_id: Optional[str] = None,
    tags: Optional[list[str] | tuple[str, ...]] = None,
    feature: Optional[str] = None,
    generation_name: Optional[str] = None,
) -> Iterator[None]:
    tokens = []
    if session_id is not None:
        tokens.append((_session_id, _session_id.set(str(session_id))))
    if user_id is not None:
        tokens.append((_user_id, _user_id.set(str(user_id))))
    if tags is not None:
        tokens.append((_tags, _tags.set(tuple(str(t) for t in tags if t))))
    if feature is not None:
        tokens.append((_feature, _feature.set(str(feature))))
    if generation_name is not None:
        tokens.append((_generation_name, _generation_name.set(str(generation_name))))
    try:
        yield
    finally:
        for var, token in reversed(tokens):
            var.reset(token)


def current_trace_metadata() -> dict[str, Any]:
    """Build OpenAI metadata dict understood by langfuse.openai."""
    metadata: dict[str, Any] = {}
    session_id = _session_id.get()
    user_id = _user_id.get()
    tags = list(_tags.get() or ())
    feature = _feature.get()
    if feature and feature not in tags:
        tags.append(feature)
    if session_id:
        metadata["langfuse_session_id"] = session_id
    if user_id:
        metadata["langfuse_user_id"] = user_id
    if tags:
        metadata["langfuse_tags"] = tags
    return metadata


def current_generation_name(default: str = "azure-chat") -> str:
    return _generation_name.get() or _feature.get() or default


def set_active_prompt(prompt: Any) -> None:
    """Remember a Langfuse prompt so the next Azure OpenAI call can link it."""
    _active_prompt.set(prompt)


def take_active_prompt() -> Any:
    """Return and clear the active Langfuse prompt (one-shot link to a generation)."""
    prompt = _active_prompt.get()
    if prompt is not None:
        _active_prompt.set(None)
    return prompt


def flush() -> None:
    if not tracing_enabled():
        return
    try:
        from langfuse import get_client

        get_client().flush()
    except Exception:
        return


def auth_check() -> bool:
    if not tracing_enabled():
        return False
    ensure_host_alias()
    try:
        from langfuse import get_client

        return bool(get_client().auth_check())
    except Exception:
        return False
