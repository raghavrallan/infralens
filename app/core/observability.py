"""Langfuse tracing context: session, user, tags, and feature labels.

Chat turns use chat_id as session_id so Langfuse Sessions group a conversation.
Authenticated username/id is attached as user_id for per-user cost and quality.

Langfuse is optional: when the host (e.g. aigovernance.mooglelabs.com) is down or
unreachable, the app continues with in-code prompt fallbacks and no tracing.
"""
from __future__ import annotations

import logging
import os
import threading
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any, Iterator, Optional

logger = logging.getLogger(__name__)

_session_id: ContextVar[Optional[str]] = ContextVar("langfuse_session_id", default=None)
_user_id: ContextVar[Optional[str]] = ContextVar("langfuse_user_id", default=None)
_tags: ContextVar[tuple[str, ...]] = ContextVar("langfuse_tags", default=())
_feature: ContextVar[Optional[str]] = ContextVar("langfuse_feature", default=None)
_generation_name: ContextVar[Optional[str]] = ContextVar(
    "langfuse_generation_name", default=None
)
# Most recently fetched Langfuse prompt object (linked on the next generation).
_active_prompt: ContextVar[Any] = ContextVar("langfuse_active_prompt", default=None)

# Process-wide circuit breaker: once Langfuse times out, skip further remote calls
# for this process so startup / chat do not stall on a dead host.
_unreachable_lock = threading.Lock()
_unreachable = False
_unreachable_reason = ""
_client_lock = threading.Lock()
_client: Any = None


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


def client_timeout_seconds() -> int:
    """HTTP timeout for Langfuse SDK calls. Keep short so a dead host cannot stall boot."""
    raw = os.environ.get("LANGFUSE_TIMEOUT", "3")
    try:
        return max(1, int(raw))
    except ValueError:
        return 3


def prompt_fetch_timeout_seconds() -> int:
    raw = os.environ.get("LANGFUSE_PROMPT_FETCH_TIMEOUT", str(client_timeout_seconds()))
    try:
        return max(1, int(raw))
    except ValueError:
        return client_timeout_seconds()


def ensure_host_alias() -> None:
    """Langfuse accepts BASE_URL; some SDK paths still read HOST."""
    base = os.environ.get("LANGFUSE_BASE_URL") or os.environ.get("LANGFUSE_HOST")
    if base:
        os.environ.setdefault("LANGFUSE_BASE_URL", base)
        os.environ.setdefault("LANGFUSE_HOST", base)


def langfuse_unreachable() -> bool:
    return _unreachable


def mark_langfuse_unreachable(reason: str) -> None:
    """Trip the circuit breaker after a timeout / connection failure."""
    global _unreachable, _unreachable_reason
    with _unreachable_lock:
        if _unreachable:
            return
        _unreachable = True
        _unreachable_reason = (reason or "unreachable").strip() or "unreachable"
        logger.warning(
            "Langfuse unavailable (%s); continuing without remote prompts/tracing for this process",
            _unreachable_reason,
        )


def reset_langfuse_circuit_for_tests() -> None:
    """Test helper only — clear circuit breaker and cached client."""
    global _unreachable, _unreachable_reason, _client
    with _unreachable_lock:
        _unreachable = False
        _unreachable_reason = ""
    with _client_lock:
        _client = None


def get_langfuse_client() -> Any:
    """Return a Langfuse client with a short timeout, or raise if tracing is off."""
    if not tracing_enabled():
        raise RuntimeError("Langfuse tracing is disabled")
    if _unreachable:
        raise RuntimeError(f"Langfuse unreachable: {_unreachable_reason or 'skipped'}")
    ensure_host_alias()
    global _client
    with _client_lock:
        if _client is None:
            from langfuse import Langfuse

            _client = Langfuse(timeout=client_timeout_seconds())
        return _client


def probe_langfuse() -> bool:
    """Fast reachability check. False means callers should use local fallbacks only."""
    if not tracing_enabled() or _unreachable:
        return False
    ensure_host_alias()
    base = (
        os.environ.get("LANGFUSE_BASE_URL")
        or os.environ.get("LANGFUSE_HOST")
        or "https://cloud.langfuse.com"
    ).rstrip("/")
    timeout = float(client_timeout_seconds())
    try:
        import httpx

        with httpx.Client(timeout=timeout) as http:
            # Prefer health; any HTTP response means the host is reachable.
            response = http.get(f"{base}/api/public/health")
            if response.status_code >= 500:
                mark_langfuse_unreachable(f"health HTTP {response.status_code}")
                return False
            return True
    except Exception as exc:  # noqa: BLE001 — optional dependency path
        mark_langfuse_unreachable(str(exc) or exc.__class__.__name__)
        return False


def bind_tracing(
    *,
    session_id: Optional[str] = None,
    user_id: Optional[str] = None,
    tags: Optional[list[str] | tuple[str, ...]] = None,
    feature: Optional[str] = None,
    generation_name: Optional[str] = None,
) -> list[tuple[ContextVar[Any], Any]]:
    """Set tracing ContextVars and return tokens for a later soft reset.

    Prefer this (or tracing_context) for request-scoped work. For StreamingResponse
    generators that yield, use bind_tracing at the start and do not reset across
    yields — ASGI may resume the generator in a different Context, which makes
    ContextVar.reset(token) raise ValueError.
    """
    tokens: list[tuple[ContextVar[Any], Any]] = []
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
    return tokens


def reset_tracing(tokens: list[tuple[ContextVar[Any], Any]]) -> None:
    """Reset ContextVar tokens; ignore cross-context errors from streamed responses."""
    for var, token in reversed(tokens):
        try:
            var.reset(token)
        except ValueError:
            # Token was created in a different Context (common with StreamingResponse).
            pass


@contextmanager
def tracing_context(
    *,
    session_id: Optional[str] = None,
    user_id: Optional[str] = None,
    tags: Optional[list[str] | tuple[str, ...]] = None,
    feature: Optional[str] = None,
    generation_name: Optional[str] = None,
) -> Iterator[None]:
    tokens = bind_tracing(
        session_id=session_id,
        user_id=user_id,
        tags=tags,
        feature=feature,
        generation_name=generation_name,
    )
    try:
        yield
    finally:
        reset_tracing(tokens)


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


def is_transport_error(exc: BaseException) -> bool:
    text = f"{exc.__class__.__name__}: {exc}".lower()
    needles = (
        "timed out",
        "timeout",
        "connection",
        "connecterror",
        "unreachable",
        "name or service not known",
        "getaddrinfo",
        "temporarily unavailable",
        "failed to establish",
    )
    return any(n in text for n in needles)


def flush() -> None:
    if not tracing_enabled() or _unreachable:
        return
    try:
        get_langfuse_client().flush()
    except Exception as exc:  # noqa: BLE001
        if is_transport_error(exc):
            mark_langfuse_unreachable(str(exc))
        return


def auth_check() -> bool:
    if not tracing_enabled() or _unreachable:
        return False
    ensure_host_alias()
    try:
        return bool(get_langfuse_client().auth_check())
    except Exception as exc:  # noqa: BLE001
        if is_transport_error(exc):
            mark_langfuse_unreachable(str(exc))
        return False
