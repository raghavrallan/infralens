"""Signed outbound webhooks for n8n (and compatible automation).

InfraLens remains the authority for Risk Engine / RBAC. Webhooks only notify
external systems; inbound actions must call FastAPI with auth.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import threading
from typing import Any, Optional
from urllib import error, request

from app.agents.runtime.flags import feature_enabled

logger = logging.getLogger(__name__)


def webhook_url() -> str:
    return (os.environ.get("N8N_WEBHOOK_URL") or "").strip()


def webhook_secret() -> str:
    return (os.environ.get("WEBHOOK_HMAC_SECRET") or os.environ.get("N8N_WEBHOOK_SECRET") or "").strip()


def integrations_enabled() -> bool:
    return feature_enabled("n8n_webhooks") and bool(webhook_url())


def sign_body(body: bytes, secret: str) -> str:
    digest = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    return f"sha256={digest}"


def verify_signature(body: bytes, header: str, secret: str) -> bool:
    if not secret or not header:
        return False
    expected = sign_body(body, secret)
    return hmac.compare_digest(expected, header.strip())


def emit_event(payload: dict[str, Any], *, timeout: float = 5.0) -> bool:
    """POST JSON payload to N8N_WEBHOOK_URL. No-op when disabled. Never raises."""
    if not integrations_enabled():
        return False
    url = webhook_url()
    try:
        body = json.dumps(payload, default=str).encode("utf-8")
    except Exception:
        logger.exception("webhook serialize failed")
        return False
    headers = {
        "Content-Type": "application/json",
        "User-Agent": "InfraLens-Webhooks/1.0",
        "X-InfraLens-Event": str(payload.get("event") or ""),
    }
    secret = webhook_secret()
    if secret:
        headers["X-InfraLens-Signature"] = sign_body(body, secret)
    req = request.Request(url, data=body, headers=headers, method="POST")
    try:
        with request.urlopen(req, timeout=timeout) as resp:
            return 200 <= getattr(resp, "status", 200) < 300
    except error.HTTPError as exc:
        logger.warning("webhook HTTP %s for %s", exc.code, payload.get("event"))
        return False
    except Exception as exc:  # noqa: BLE001
        logger.warning("webhook failed for %s: %s", payload.get("event"), exc)
        return False


def emit_event_async(payload: dict[str, Any]) -> None:
    """Fire-and-forget so request/worker latency is not blocked on n8n."""
    if not integrations_enabled():
        return

    def _run() -> None:
        emit_event(payload)

    threading.Thread(target=_run, name="infralens-webhook", daemon=True).start()
