"""DB-backed users and JWT authentication for the InfraLens UI."""
from __future__ import annotations

import hashlib
import hmac
import os
import secrets
import time
import uuid
from typing import Any, Optional

import jwt
from fastapi import Header, HTTPException
from sqlalchemy import select

from app.db import SessionLocal, User

DEFAULT_USERNAME = "admin"
DEFAULT_PASSWORD = "infralens"
DEFAULT_DISPLAY_NAME = "Admin"
TOKEN_TTL_SECONDS = 60 * 60 * 24 * 7  # 7 days
JWT_ALGORITHM = "HS256"
_PBKDF2_ROUNDS = 120_000


def _jwt_secret() -> str:
    return (
        os.environ.get("AUTH_JWT_SECRET")
        or os.environ.get("AUTH_SESSION_SECRET")
        or os.environ.get("EXECUTOR_SERVICE_KEY")
        or "infralens-dev-jwt-secret"
    )


def _seed_username() -> str:
    return (os.environ.get("AUTH_USERNAME") or DEFAULT_USERNAME).strip() or DEFAULT_USERNAME


def _seed_password() -> str:
    return os.environ.get("AUTH_PASSWORD") or DEFAULT_PASSWORD


def _seed_display_name() -> str:
    return (
        (os.environ.get("AUTH_DISPLAY_NAME") or DEFAULT_DISPLAY_NAME).strip()
        or DEFAULT_DISPLAY_NAME
    )


def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt.encode("utf-8"),
        _PBKDF2_ROUNDS,
    ).hex()
    return f"pbkdf2_sha256${_PBKDF2_ROUNDS}${salt}${digest}"


def verify_password(password: str, password_hash: str) -> bool:
    try:
        algo, rounds_raw, salt, expected = password_hash.split("$", 3)
    except ValueError:
        return False
    if algo != "pbkdf2_sha256":
        return False
    try:
        rounds = int(rounds_raw)
    except ValueError:
        return False
    digest = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt.encode("utf-8"),
        rounds,
    ).hex()
    return hmac.compare_digest(digest, expected)


def _public_user(user: User) -> dict[str, Any]:
    return {
        "id": user.id,
        "username": user.username,
        "name": user.display_name,
    }


def ensure_seed_user() -> None:
    """Create the bootstrap admin user when the users table is empty."""
    with SessionLocal() as session:
        if session.scalar(select(User.id).limit(1)) is not None:
            return
        session.add(
            User(
                id=str(uuid.uuid4()),
                username=_seed_username(),
                display_name=_seed_display_name(),
                password_hash=hash_password(_seed_password()),
                is_active=True,
            )
        )
        session.commit()


def authenticate(username: str, password: str) -> Optional[dict[str, Any]]:
    """Validate credentials against the users table and return a JWT session."""
    clean_user = (username or "").strip()
    if not clean_user or password is None:
        return None
    with SessionLocal() as session:
        user = session.scalar(select(User).where(User.username == clean_user))
        if user is None or not user.is_active:
            return None
        if not verify_password(password, user.password_hash):
            return None
        expires = int(time.time()) + TOKEN_TTL_SECONDS
        token = jwt.encode(
            {
                "sub": user.id,
                "username": user.username,
                "name": user.display_name,
                "exp": expires,
            },
            _jwt_secret(),
            algorithm=JWT_ALGORITHM,
        )
        return {
            "token": token,
            "token_type": "bearer",
            "user": _public_user(user),
            "expires_at": expires,
        }


def verify_token(token: str | None) -> Optional[dict[str, Any]]:
    """Decode a JWT and return the public user payload when valid."""
    if not token:
        return None
    try:
        payload = jwt.decode(token, _jwt_secret(), algorithms=[JWT_ALGORITHM])
    except jwt.PyJWTError:
        return None
    user_id = payload.get("sub")
    if not user_id:
        return None
    with SessionLocal() as session:
        user = session.get(User, str(user_id))
        if user is None or not user.is_active:
            return None
        return _public_user(user)


def bearer_token(authorization: Optional[str]) -> Optional[str]:
    if not authorization:
        return None
    scheme, _, value = authorization.partition(" ")
    if scheme.lower() != "bearer" or not value.strip():
        return None
    return value.strip()


def require_user(authorization: Optional[str] = Header(default=None)) -> dict[str, Any]:
    """FastAPI dependency: require a valid Bearer JWT."""
    user = verify_token(bearer_token(authorization))
    if user is None:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return user
