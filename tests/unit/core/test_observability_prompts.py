"""Langfuse tracing context, enablement, and prompt fallbacks."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from app.core import observability, prompts


@pytest.fixture(autouse=True)
def _reset_langfuse_circuit():
    observability.reset_langfuse_circuit_for_tests()
    yield
    observability.reset_langfuse_circuit_for_tests()


@pytest.mark.unit
def test_tracing_disabled_without_keys(monkeypatch):
    monkeypatch.delenv("LANGFUSE_PUBLIC_KEY", raising=False)
    monkeypatch.delenv("LANGFUSE_SECRET_KEY", raising=False)
    monkeypatch.setenv("LANGFUSE_TRACING_ENABLED", "true")
    assert observability.tracing_enabled() is False


@pytest.mark.unit
def test_tracing_explicitly_disabled(monkeypatch):
    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk")
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "sk")
    monkeypatch.setenv("LANGFUSE_TRACING_ENABLED", "false")
    assert observability.tracing_enabled() is False


@pytest.mark.unit
def test_tracing_enabled_when_keys_present(monkeypatch):
    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk")
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "sk")
    monkeypatch.setenv("LANGFUSE_TRACING_ENABLED", "true")
    assert observability.tracing_enabled() is True


@pytest.mark.unit
def test_ensure_host_alias_copies_base_url(monkeypatch):
    monkeypatch.delenv("LANGFUSE_HOST", raising=False)
    monkeypatch.setenv("LANGFUSE_BASE_URL", "https://lf.example")
    observability.ensure_host_alias()
    assert __import__("os").environ.get("LANGFUSE_HOST") == "https://lf.example"


@pytest.mark.unit
def test_tracing_context_sets_and_resets_metadata():
    with observability.tracing_context(
        session_id="chat-1",
        user_id="alice",
        tags=["chat"],
        feature="skill",
        generation_name="gen",
    ):
        meta = observability.current_trace_metadata()
        assert meta["langfuse_session_id"] == "chat-1"
        assert meta["langfuse_user_id"] == "alice"
        assert "chat" in meta["langfuse_tags"]
        assert "skill" in meta["langfuse_tags"]
        assert observability.current_generation_name() == "gen"
    assert observability.current_trace_metadata() == {}


@pytest.mark.unit
def test_reset_tracing_clears_bound_values():
    tokens = observability.bind_tracing(session_id="s1", user_id="u1")
    assert observability.current_trace_metadata()["langfuse_session_id"] == "s1"
    observability.reset_tracing(tokens)
    assert "langfuse_session_id" not in observability.current_trace_metadata()


@pytest.mark.unit
def test_active_prompt_is_one_shot():
    observability.set_active_prompt("prompt-obj")
    assert observability.take_active_prompt() == "prompt-obj"
    assert observability.take_active_prompt() is None


@pytest.mark.unit
def test_flush_and_auth_check_short_circuit_when_disabled(monkeypatch):
    monkeypatch.delenv("LANGFUSE_PUBLIC_KEY", raising=False)
    monkeypatch.delenv("LANGFUSE_SECRET_KEY", raising=False)
    observability.flush()
    assert observability.auth_check() is False


@pytest.mark.unit
def test_fallback_compile_substitutes_known_variables_only():
    template = "Hello {{ name }} and {{ missing }}"
    assert prompts._fallback_compile(template, None) == template
    assert prompts._fallback_compile(template, {"name": "Pat"}) == "Hello Pat and {{ missing }}"


@pytest.mark.unit
def test_get_text_prompt_uses_fallback_when_tracing_off(monkeypatch):
    monkeypatch.delenv("LANGFUSE_PUBLIC_KEY", raising=False)
    result = prompts.get_text_prompt(
        "x", fallback="Hi {{ who }}", variables={"who": "team"}
    )
    assert result == "Hi team"


@pytest.mark.unit
def test_get_text_prompt_degrades_on_langfuse_error(monkeypatch):
    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk")
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "sk")
    monkeypatch.setenv("LANGFUSE_TRACING_ENABLED", "true")
    with patch("app.core.observability.tracing_enabled", return_value=True):
        with patch(
            "app.core.observability.get_langfuse_client",
            side_effect=RuntimeError("timed out"),
        ):
            result = prompts.get_text_prompt("x", fallback="local")
    assert result == "local"
    assert observability.langfuse_unreachable() is True


@pytest.mark.unit
def test_seed_skips_when_probe_fails(monkeypatch):
    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk")
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "sk")
    monkeypatch.setenv("LANGFUSE_TRACING_ENABLED", "true")
    with patch("app.core.observability.probe_langfuse", return_value=False):
        with patch("app.core.prompts.ensure_text_prompt") as ensure:
            prompts.seed_core_prompts()
    ensure.assert_not_called()


@pytest.mark.unit
def test_ensure_and_seed_are_noops_when_tracing_disabled(monkeypatch):
    monkeypatch.delenv("LANGFUSE_PUBLIC_KEY", raising=False)
    prompts.ensure_text_prompt("n", "p")
    prompts.seed_core_prompts()


@pytest.mark.unit
def test_probe_marks_unreachable_on_timeout(monkeypatch):
    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk")
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "sk")
    monkeypatch.setenv("LANGFUSE_TRACING_ENABLED", "true")
    monkeypatch.setenv("LANGFUSE_BASE_URL", "https://langfuse.example")
    monkeypatch.setenv("LANGFUSE_TIMEOUT", "1")

    class _Boom:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def get(self, *_args, **_kwargs):
            raise TimeoutError("timed out")

    with patch("httpx.Client", return_value=_Boom()):
        assert observability.probe_langfuse() is False
    assert observability.langfuse_unreachable() is True
