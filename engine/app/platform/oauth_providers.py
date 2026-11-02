"""Provider OAuth helpers (GitHub App / Azure device-code) when env is configured."""
from __future__ import annotations

import os
import secrets
import time
from typing import Any, Optional
from urllib.parse import urlencode

import httpx

from app.platform import connections

# In-memory OAuth state (MVP). Survives one process; fine for Container App sticky sessions.
_OAUTH_STATE: dict[str, dict[str, Any]] = {}


def github_oauth_configured() -> bool:
    return bool(os.environ.get("GITHUB_OAUTH_CLIENT_ID") and os.environ.get("GITHUB_OAUTH_CLIENT_SECRET"))


def azure_oauth_configured() -> bool:
    return bool(
        os.environ.get("AZURE_OAUTH_CLIENT_ID")
        and os.environ.get("AZURE_OAUTH_CLIENT_SECRET")
        and os.environ.get("AZURE_OAUTH_TENANT_ID")
    )


def auth_options() -> dict[str, Any]:
    gh_oauth = github_oauth_configured()
    az_oauth = azure_oauth_configured()
    return {
        "github": {
            "oauth": gh_oauth,
            "pat": True,
            # Always expose oauth in methods so the UI can show the SSO option;
            # start endpoint returns a clear error when env is missing.
            "methods": ["oauth", "token"],
            "oauth_note": (
                None
                if gh_oauth
                else (
                    "Add GITHUB_OAUTH_CLIENT_ID and GITHUB_OAUTH_CLIENT_SECRET to .env "
                    "(GitHub → Settings → Developer settings → OAuth Apps). "
                    f"Callback URL: {os.environ.get('PUBLIC_APP_URL', 'http://127.0.0.1:8000')}"
                    "/api/providers/github/oauth/callback"
                )
            ),
        },
        "azure": {
            "oauth": az_oauth,
            "secrets": True,
            "methods": ["oauth", "client_secret"],
            "oauth_note": (
                None
                if az_oauth
                else "Coming with app registration — use client secret for production now."
            ),
        },
    }


def _api_public_base(request_base: str) -> str:
    """Base URL GitHub redirects to (must hit the API callback route)."""
    return (
        os.environ.get("OAUTH_REDIRECT_BASE")
        or os.environ.get("DEV_API_ORIGIN")
        or os.environ.get("CONTROL_PLANE_URL")
        or request_base.rstrip("/")
    ).rstrip("/")


def _frontend_public_base() -> str:
    return (
        os.environ.get("PUBLIC_APP_URL")
        or os.environ.get("FRONTEND_URL")
        or "http://127.0.0.1:3000"
    ).rstrip("/")


def _public_base(request_base: str) -> str:
    # Kept for callers; OAuth callback must land on the API.
    return _api_public_base(request_base)


def start_github_oauth(
    *,
    project_id: str,
    request_base: str,
    return_to: str = "onboarding",
) -> dict[str, Any]:
    if not github_oauth_configured():
        raise RuntimeError(
            "GitHub OAuth is not configured. Set GITHUB_OAUTH_CLIENT_ID and "
            "GITHUB_OAUTH_CLIENT_SECRET in .env, then restart the API."
        )
    state = secrets.token_urlsafe(24)
    _OAUTH_STATE[state] = {
        "provider": "github",
        "project_id": project_id,
        "return_to": return_to or "onboarding",
        "created_at": time.time(),
    }
    redirect_uri = f"{_api_public_base(request_base)}/api/providers/github/oauth/callback"
    params = urlencode(
        {
            "client_id": os.environ["GITHUB_OAUTH_CLIENT_ID"],
            "redirect_uri": redirect_uri,
            "scope": "repo read:org user:email",
            "state": state,
        }
    )
    return {
        "authorize_url": f"https://github.com/login/oauth/authorize?{params}",
        "state": state,
        "redirect_uri": redirect_uri,
    }


def finish_github_oauth(*, code: str, state: str, request_base: str) -> dict[str, Any]:
    meta = _OAUTH_STATE.pop(state, None)
    if not meta or meta.get("provider") != "github":
        raise ValueError("Invalid or expired OAuth state")
    project_id = meta["project_id"]
    return_to = meta.get("return_to") or "onboarding"
    redirect_uri = f"{_api_public_base(request_base)}/api/providers/github/oauth/callback"
    with httpx.Client(timeout=30.0) as client:
        token_resp = client.post(
            "https://github.com/login/oauth/access_token",
            headers={"Accept": "application/json"},
            data={
                "client_id": os.environ["GITHUB_OAUTH_CLIENT_ID"],
                "client_secret": os.environ["GITHUB_OAUTH_CLIENT_SECRET"],
                "code": code,
                "redirect_uri": redirect_uri,
            },
        )
        token_resp.raise_for_status()
        token_body = token_resp.json()
        access_token = token_body.get("access_token")
        if not access_token:
            raise RuntimeError(token_body.get("error_description") or "GitHub OAuth token exchange failed")
        user_resp = client.get(
            "https://api.github.com/user",
            headers={
                "Authorization": f"Bearer {access_token}",
                "Accept": "application/vnd.github+json",
            },
        )
        user_resp.raise_for_status()
        user = user_resp.json()
    status = connections.set_connection(
        project_id,
        "github",
        "oauth",
        {
            "token": access_token,
            "username": user.get("login") or "",
        },
    )
    return {
        "project_id": project_id,
        "connection": status,
        "identity": user.get("login"),
        "return_to": return_to,
        "frontend_redirect": (
            f"{_frontend_public_base()}/onboarding?oauth=github&ok=1"
            f"&project_id={project_id}"
            if return_to == "onboarding"
            else f"{_frontend_public_base()}/settings?oauth=github&ok=1&project_id={project_id}"
        ),
    }


def start_azure_oauth(*, project_id: str, request_base: str) -> dict[str, Any]:
    if not azure_oauth_configured():
        raise RuntimeError(
            "Azure OAuth is not configured. Use client_secret method, or set "
            "AZURE_OAUTH_CLIENT_ID/SECRET/TENANT_ID."
        )
    state = secrets.token_urlsafe(24)
    _OAUTH_STATE[state] = {
        "provider": "azure",
        "project_id": project_id,
        "created_at": time.time(),
    }
    tenant = os.environ["AZURE_OAUTH_TENANT_ID"]
    redirect_uri = f"{_public_base(request_base)}/api/providers/azure/oauth/callback"
    params = urlencode(
        {
            "client_id": os.environ["AZURE_OAUTH_CLIENT_ID"],
            "response_type": "code",
            "redirect_uri": redirect_uri,
            "response_mode": "query",
            "scope": "https://management.azure.com/user_impersonation offline_access openid profile",
            "state": state,
        }
    )
    return {
        "authorize_url": f"https://login.microsoftonline.com/{tenant}/oauth2/v2.0/authorize?{params}",
        "state": state,
        "redirect_uri": redirect_uri,
        "note": "Device-code alternative available via app registration.",
    }


def finish_azure_oauth(*, code: str, state: str, request_base: str) -> dict[str, Any]:
    meta = _OAUTH_STATE.pop(state, None)
    if not meta or meta.get("provider") != "azure":
        raise ValueError("Invalid or expired OAuth state")
    project_id = meta["project_id"]
    tenant = os.environ["AZURE_OAUTH_TENANT_ID"]
    redirect_uri = f"{_public_base(request_base)}/api/providers/azure/oauth/callback"
    with httpx.Client(timeout=30.0) as client:
        token_resp = client.post(
            f"https://login.microsoftonline.com/{tenant}/oauth2/v2.0/token",
            data={
                "client_id": os.environ["AZURE_OAUTH_CLIENT_ID"],
                "client_secret": os.environ["AZURE_OAUTH_CLIENT_SECRET"],
                "code": code,
                "redirect_uri": redirect_uri,
                "grant_type": "authorization_code",
            },
        )
        token_resp.raise_for_status()
        token_body = token_resp.json()
        access_token = token_body.get("access_token")
        if not access_token:
            raise RuntimeError(token_body.get("error_description") or "Azure OAuth token exchange failed")
    status = connections.set_connection(
        project_id,
        "azure",
        "oauth",
        {
            "tenant_id": tenant,
            "client_id": os.environ["AZURE_OAUTH_CLIENT_ID"],
            "client_secret": os.environ["AZURE_OAUTH_CLIENT_SECRET"],
            "access_token": access_token,
            "subscription_id": os.environ.get("AZURE_OAUTH_SUBSCRIPTION_ID", ""),
        },
    )
    return {"project_id": project_id, "connection": status}
