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
from fastapi import Header, HTTPException, Request
from sqlalchemy import select, text

from app.core.db import SessionLocal, User, engine
from app.core.rbac import ROLE_LABELS, normalize_role

DEFAULT_USERNAME = "admin"
DEFAULT_PASSWORD = "infralens"
DEFAULT_DISPLAY_NAME = "Admin"
TOKEN_TTL_SECONDS = 60 * 60 * 24 * 7  # 7 days
JWT_ALGORITHM = "HS256"
_PBKDF2_ROUNDS = 120_000
# Per-request DB revalidation adds a full RTT on every /api call. Default off:
# trust signed JWT claims (role/active checked at login). Set AUTH_VERIFY_DB=true
# when immediate revoke-on-deactivate is required.
_USER_CACHE_TTL = float(os.environ.get("AUTH_USER_CACHE_TTL", "60"))
_user_cache: dict[str, tuple[float, dict[str, Any]]] = {}


def _jwt_secret() -> str:
    return (
        os.environ.get("AUTH_JWT_SECRET")
        or os.environ.get("AUTH_SESSION_SECRET")
        or os.environ.get("EXECUTOR_SERVICE_KEY")
        or "infralens-dev-jwt-secret"
    )


def _verify_db_enabled() -> bool:
    return os.environ.get("AUTH_VERIFY_DB", "false").lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def _public_from_claims(payload: dict[str, Any]) -> Optional[dict[str, Any]]:
    user_id = payload.get("sub")
    username = payload.get("username")
    if not user_id or not username:
        return None
    role = normalize_role(payload.get("role") or "developer")
    return {
        "id": str(user_id),
        "username": str(username),
        "name": str(payload.get("name") or username),
        "role": role,
        "role_label": ROLE_LABELS.get(role, role),
        "is_active": True,
        "org_ids": list(payload.get("org_ids") or []),
    }


def _load_user_from_db(user_id: str) -> Optional[dict[str, Any]]:
    now = time.monotonic()
    cached = _user_cache.get(user_id)
    if cached is not None and cached[0] > now:
        return cached[1]
    with SessionLocal() as session:
        user = session.get(User, user_id)
        if user is None or not user.is_active:
            _user_cache.pop(user_id, None)
            return None
        public = _public_user(user)
    _user_cache[user_id] = (now + _USER_CACHE_TTL, public)
    return public


def invalidate_user_cache(user_id: Optional[str] = None) -> None:
    """Drop cached auth lookups after role/active changes."""
    if user_id is None:
        _user_cache.clear()
    else:
        _user_cache.pop(str(user_id), None)


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
    role = normalize_role(getattr(user, "role", None) or "developer")
    return {
        "id": user.id,
        "username": user.username,
        "email": getattr(user, "email", "") or "",
        "name": user.display_name,
        "role": role,
        "role_label": ROLE_LABELS.get(role, role),
        "is_active": bool(user.is_active),
    }


def ensure_seed_user() -> None:
    """Create the bootstrap Super Admin when the users table is empty.

    Also promotes AUTH_USERNAME to super_admin and backfills missing roles.
    """
    seed_username = _seed_username()
    with SessionLocal() as session:
        # Backfill role column if migration added it with default.
        try:
            with engine.begin() as conn:
                conn.execute(
                    text(
                        "UPDATE users SET role = 'developer' "
                        "WHERE role IS NULL OR role = ''"
                    )
                )
        except Exception:
            pass

        existing = session.scalar(select(User).where(User.username == seed_username))
        if existing is None and session.scalar(select(User.id).limit(1)) is None:
            session.add(
                User(
                    id=str(uuid.uuid4()),
                    username=seed_username,
                    display_name=_seed_display_name(),
                    password_hash=hash_password(_seed_password()),
                    role="super_admin",
                    is_active=True,
                )
            )
            session.commit()
            return

        if existing is not None:
            # Seed account is always Super Admin for bootstrap ops.
            if normalize_role(getattr(existing, "role", None)) != "super_admin":
                existing.role = "super_admin"
                session.commit()
            return

        # Table has users but not the seed username — leave them alone.


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
        public = _public_user(user)
        try:
            from app.tenancy import memberships

            public = memberships.enrich_user_public(public)
        except Exception:
            pass
        token = jwt.encode(
            {
                "sub": user.id,
                "username": user.username,
                "name": user.display_name,
                "role": public["role"],
                "org_ids": public.get("org_ids") or [],
                "exp": expires,
            },
            _jwt_secret(),
            algorithm=JWT_ALGORITHM,
        )
        return {
            "token": token,
            "token_type": "bearer",
            "user": public,
            "expires_at": expires,
        }


def verify_token(token: str | None) -> Optional[dict[str, Any]]:
    """Decode a JWT and return the public user payload when valid.

    By default trusts signed claims (no DB round-trip). When AUTH_VERIFY_DB is
    enabled, re-loads the user from Postgres with a short in-memory TTL cache.
    """
    if not token:
        return None
    try:
        payload = jwt.decode(token, _jwt_secret(), algorithms=[JWT_ALGORITHM])
    except jwt.PyJWTError:
        return None
    user_id = payload.get("sub")
    if not user_id:
        return None
    if _verify_db_enabled():
        return _load_user_from_db(str(user_id))
    return _public_from_claims(payload)


def bearer_token(authorization: Optional[str]) -> Optional[str]:
    if not authorization:
        return None
    scheme, _, value = authorization.partition(" ")
    if scheme.lower() != "bearer" or not value.strip():
        return None
    return value.strip()


def require_user(
    request: Request,
    authorization: Optional[str] = Header(default=None),
) -> dict[str, Any]:
    """FastAPI dependency: require a valid Bearer JWT.

    Reuses ``request.state.user`` when JwtAuthMiddleware already verified the
    token so routes do not decode (or hit the DB) a second time.
    """
    existing = getattr(request.state, "user", None)
    if isinstance(existing, dict) and existing.get("id"):
        return existing
    user = verify_token(bearer_token(authorization))
    if user is None:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return user
