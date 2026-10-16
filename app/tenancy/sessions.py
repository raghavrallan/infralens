"""Postgres browser sessions. Logout and expiry drop the row's usefulness.

Phase 3 attaches the ``il_session`` cookie. This module only stores and reads
the row: SHA-256 token hash, user id, org id, and expiry.
"""
from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from app.core.db import LoginSession, SessionLocal

MAX_AGE_SECONDS = 60 * 60 * 12


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def create_session(user_id: str, org_id: Optional[str]) -> str:
    token = secrets.token_hex(32)
    expires_at = datetime.now(timezone.utc) + timedelta(seconds=MAX_AGE_SECONDS)
    with SessionLocal() as session:
        session.add(
            LoginSession(
                token_hash=_token_hash(token),
                user_id=user_id,
                org_id=org_id,
                expires_at=expires_at,
            )
        )
        session.commit()
    return token


def read_session(token: Optional[str]) -> Optional[dict[str, Any]]:
    if not token:
        return None
    with SessionLocal() as session:
        row = session.get(LoginSession, _token_hash(token))
        if row is None or row.expires_at is None:
            return None
        expires_at = row.expires_at
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)
        if expires_at < datetime.now(timezone.utc):
            return None
        return {
            "token_hash": row.token_hash,
            "user_id": row.user_id,
            "org_id": row.org_id,
            "expires_at": expires_at,
        }
