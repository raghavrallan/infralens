"""AES-256-GCM payloads compatible with infralens-live ``src/lib/crypto.js``.

The key is scrypt(APP_SECRET, salt ``infralens-live-v1``, 32 bytes). The stored
form is ``iv.tag.body``, each piece standard base64. When ``APP_SECRET`` is
unset, the key material is a generated ``data/app-secret`` file (mode 0600).
That file is local only and is not the system of record.
"""
from __future__ import annotations

import base64
import hashlib
import os
import secrets
from pathlib import Path

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

_SALT = b"infralens-live-v1"
_READ_ERROR = "Stored Azure secret could not be read."


def _secret_file() -> Path:
    return Path.cwd() / "data" / "app-secret"


def secret_material() -> str:
    env = os.environ.get("APP_SECRET", "").strip()
    if env:
        return env
    path = _secret_file()
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(secrets.token_hex(32), encoding="utf-8")
        path.chmod(0o600)
    return path.read_text(encoding="utf-8").strip()


def _key() -> bytes:
    return hashlib.scrypt(
        secret_material().encode("utf-8"),
        salt=_SALT,
        n=2**14,
        r=8,
        p=1,
        dklen=32,
    )


def encrypt(plain: str) -> str:
    iv = secrets.token_bytes(12)
    encrypted = AESGCM(_key()).encrypt(iv, str(plain).encode("utf-8"), None)
    body, tag = encrypted[:-16], encrypted[-16:]
    return ".".join(base64.b64encode(part).decode("ascii") for part in (iv, tag, body))


def decrypt(payload: str) -> str:
    parts = str(payload or "").split(".")
    if len(parts) != 3 or not all(parts):
        raise ValueError(_READ_ERROR)
    try:
        iv, tag, body = (base64.b64decode(part) for part in parts)
        plain = AESGCM(_key()).decrypt(iv, body + tag, None)
    except Exception as exc:
        raise ValueError(_READ_ERROR) from exc
    return plain.decode("utf-8")
