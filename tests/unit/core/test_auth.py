"""Password hashing, JWT verification, and bearer parsing — no database."""
from __future__ import annotations

import time

import jwt
import pytest

from app.core import auth


@pytest.mark.unit
def test_hash_and_verify_password_round_trip():
    hashed = auth.hash_password("correct-horse")
    assert hashed.startswith("pbkdf2_sha256$")
    assert auth.verify_password("correct-horse", hashed)
    assert not auth.verify_password("wrong", hashed)
    assert hashed != auth.hash_password("correct-horse")


@pytest.mark.unit
def test_verify_password_rejects_malformed_hashes():
    assert not auth.verify_password("x", "not-a-hash")
    assert not auth.verify_password("x", "sha256$1$salt$digest")
    assert not auth.verify_password("x", "pbkdf2_sha256$notint$salt$digest")


@pytest.mark.unit
def test_bearer_token_parsing():
    assert auth.bearer_token(None) is None
    assert auth.bearer_token("") is None
    assert auth.bearer_token("Basic abc") is None
    assert auth.bearer_token("Bearer") is None
    assert auth.bearer_token("Bearer   ") is None
    assert auth.bearer_token("Bearer tok-123") == "tok-123"
    assert auth.bearer_token("bearer tok-123") == "tok-123"


@pytest.mark.unit
def test_verify_token_rejects_missing_invalid_and_expired(monkeypatch):
    monkeypatch.setenv("AUTH_JWT_SECRET", "unit-secret")
    assert auth.verify_token(None) is None
    assert auth.verify_token("") is None
    assert auth.verify_token("not.a.jwt") is None
    expired = jwt.encode(
        {
            "sub": "u1",
            "username": "alice",
            "role": "developer",
            "exp": int(time.time()) - 10,
        },
        "unit-secret",
        algorithm=auth.JWT_ALGORITHM,
    )
    assert auth.verify_token(expired) is None


@pytest.mark.unit
def test_verify_token_accepts_valid_claims(monkeypatch):
    monkeypatch.setenv("AUTH_JWT_SECRET", "unit-secret")
    token = jwt.encode(
        {
            "sub": "user-1",
            "username": "alice",
            "name": "Alice",
            "role": "org_admin",
            "org_ids": ["org-a"],
            "exp": int(time.time()) + 3600,
        },
        "unit-secret",
        algorithm=auth.JWT_ALGORITHM,
    )
    public = auth.verify_token(token)
    assert public is not None
    assert public["id"] == "user-1"
    assert public["username"] == "alice"
    assert public["role"] == "org_admin"
    assert public["org_ids"] == ["org-a"]
    assert public["is_active"] is True


@pytest.mark.unit
def test_verify_token_rejects_payload_without_subject(monkeypatch):
    monkeypatch.setenv("AUTH_JWT_SECRET", "unit-secret")
    token = jwt.encode(
        {"username": "alice", "exp": int(time.time()) + 3600},
        "unit-secret",
        algorithm=auth.JWT_ALGORITHM,
    )
    assert auth.verify_token(token) is None


@pytest.mark.unit
def test_public_from_claims_requires_id_and_username():
    assert auth._public_from_claims({"username": "a"}) is None
    assert auth._public_from_claims({"sub": "1"}) is None
    public = auth._public_from_claims({"sub": "1", "username": "a", "role": "lead"})
    assert public["role"] == "devops_lead"


@pytest.mark.unit
def test_invalidate_user_cache_clears_entries():
    auth._user_cache["u1"] = (time.monotonic() + 60, {"id": "u1"})
    auth._user_cache["u2"] = (time.monotonic() + 60, {"id": "u2"})
    auth.invalidate_user_cache("u1")
    assert "u1" not in auth._user_cache
    assert "u2" in auth._user_cache
    auth.invalidate_user_cache()
    assert auth._user_cache == {}


@pytest.mark.unit
def test_authenticate_rejects_empty_credentials(monkeypatch):
    monkeypatch.setattr(auth, "SessionLocal", None)
    assert auth.authenticate("", "x") is None
    assert auth.authenticate("  ", "x") is None
    assert auth.authenticate("alice", None) is None
