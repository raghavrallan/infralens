"""Provider connection store, backed by Postgres and scoped per project.

Persists connection details for Azure, AWS and GitHub in the `connections`
table, keyed by (project_id, provider), so each project carries its own
credentials. Secret values are never returned to the client — only a masked
hint and connection metadata.

Supported connection methods:
  - Azure  : "client_secret" (tenant/client/secret/subscription) or "sso"
  - AWS    : "access_key" (access key id/secret/region) or "sso"
  - GitHub : "token" (personal access token) or "sso"
"""
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.exc import ProgrammingError

from app.db import Connection, SessionLocal

PROVIDERS = ("azure", "aws", "github")

_IDENTITY_FIELD = {
    "azure": "client_id",
    "aws": "access_key_id",
    "github": "username",
}
_SECRET_FIELDS = {
    "client_secret",
    "secret_access_key",
    "token",
    "password",
}


def _mask(value: str) -> str:
    if not value:
        return ""
    if len(value) <= 4:
        return "*" * len(value)
    return f"{'*' * (len(value) - 4)}{value[-4:]}"


def _first_secret(fields: dict[str, Any]) -> str:
    for key in fields:
        if key in _SECRET_FIELDS:
            return str(fields[key])
    return ""


def set_connection(
    project_id: str, provider: str, method: str, fields: dict[str, Any]
) -> dict[str, Any]:
    """Save (upsert) a connection for a provider within a project."""
    if provider not in PROVIDERS:
        raise ValueError(f"Unknown provider: {provider}")
    clean = {k: v for k, v in fields.items() if v not in (None, "")}
    with SessionLocal() as session:
        row = session.get(Connection, {"project_id": project_id, "provider": provider})
        if row is None:
            session.add(
                Connection(
                    project_id=project_id, provider=provider, method=method, fields=clean
                )
            )
        else:
            row.method = method
            row.fields = clean
        session.commit()
    return status(project_id, provider)


def remove_connection(project_id: str, provider: str) -> dict[str, Any]:
    """Disconnect a provider within a project and return its (empty) status."""
    if provider not in PROVIDERS:
        raise ValueError(f"Unknown provider: {provider}")
    with SessionLocal() as session:
        row = session.get(Connection, {"project_id": project_id, "provider": provider})
        if row is not None:
            try:
                with session.begin_nested():
                    session.delete(row)
            except ProgrammingError:
                # Azure app role may lack DELETE on root_admin-owned connections.
                row.method = ""
                row.fields = {}
            session.commit()
    return status(project_id, provider)


def status(project_id: str, provider: str) -> dict[str, Any]:
    """Return the public (secret-free) status for one provider in a project."""
    with SessionLocal() as session:
        row = session.get(Connection, {"project_id": project_id, "provider": provider})
        if row is None or not (row.method or "").strip():
            return {"provider": provider, "connected": False}
        fields = row.fields or {}
        identity_key = _IDENTITY_FIELD.get(provider, "")
        return {
            "provider": provider,
            "connected": True,
            "method": row.method,
            "identity": fields.get(identity_key, ""),
            "hint": _mask(_first_secret(fields)),
            "connected_at": row.connected_at.isoformat() if row.connected_at else None,
        }


def all_status(project_id: str) -> list[dict[str, Any]]:
    """Return public status for every known provider in a project."""
    return [status(project_id, p) for p in PROVIDERS]


def get_secret_fields(project_id: str, provider: str) -> Optional[dict[str, Any]]:
    """Return raw stored fields for internal use by providers (never sent to UI)."""
    with SessionLocal() as session:
        row = session.get(Connection, {"project_id": project_id, "provider": provider})
        return dict(row.fields) if row is not None else None
