"""Application configuration, backed by Postgres.

Azure OpenAI settings live in the `app_config` table and are managed from the
Settings page — not environment variables. Infrastructure-only values (server
host/port) still come from the environment.
"""
import os
import time
from dataclasses import dataclass

from sqlalchemy import select

from app.core.db import AppConfig, SessionLocal

_AZURE_KEYS = (
    "azure_openai_endpoint",
    "azure_openai_api_key",
    "azure_openai_deployment",
    "azure_openai_api_version",
)
_DEFAULTS = {
    "azure_openai_deployment": "gpt-4o",
    "azure_openai_api_version": "2024-10-21",
}
_AZURE_CACHE_TTL = float(os.environ.get("AZURE_CONFIG_CACHE_TTL", "60"))
_azure_cache: tuple[float, "AzureConfig"] | None = None


@dataclass
class AzureConfig:
    """Resolved Azure OpenAI configuration."""

    endpoint: str = ""
    api_key: str = ""
    deployment: str = "gpt-4o"
    api_version: str = "2024-10-21"

    @property
    def configured(self) -> bool:
        return bool(self.endpoint and self.api_key)


def get_config_value(key: str, default: str = "") -> str:
    with SessionLocal() as session:
        row = session.get(AppConfig, key)
        if row is not None and row.value:
            return row.value
    return default


def set_config_values(values: dict[str, str]) -> None:
    """Insert/update a batch of config keys."""
    with SessionLocal() as session:
        for key, value in values.items():
            row = session.get(AppConfig, key)
            if row is None:
                session.add(AppConfig(key=key, value=value))
            else:
                row.value = value
        session.commit()
    invalidate_azure_config_cache()


def get_azure_config(*, use_cache: bool = True) -> AzureConfig:
    """Load Azure OpenAI settings from the database (short TTL cache)."""
    global _azure_cache
    if use_cache and _azure_cache is not None:
        expires_at, cached = _azure_cache
        if expires_at > time.monotonic():
            return cached

    values: dict[str, str] = {}
    with SessionLocal() as session:
        rows = session.execute(
            select(AppConfig).where(AppConfig.key.in_(_AZURE_KEYS))
        ).scalars()
        for row in rows:
            if row.value:
                values[row.key] = row.value

    config = AzureConfig(
        endpoint=values.get("azure_openai_endpoint", ""),
        api_key=values.get("azure_openai_api_key", ""),
        deployment=values.get(
            "azure_openai_deployment", _DEFAULTS["azure_openai_deployment"]
        ),
        api_version=values.get(
            "azure_openai_api_version", _DEFAULTS["azure_openai_api_version"]
        ),
    )
    _azure_cache = (time.monotonic() + _AZURE_CACHE_TTL, config)
    return config


def invalidate_azure_config_cache() -> None:
    global _azure_cache
    _azure_cache = None


def set_azure_config(
    endpoint: str,
    api_key: str,
    deployment: str,
    api_version: str,
) -> AzureConfig:
    """Persist Azure OpenAI settings. An empty api_key leaves the stored key."""
    values = {
        "azure_openai_endpoint": endpoint,
        "azure_openai_deployment": deployment or _DEFAULTS["azure_openai_deployment"],
        "azure_openai_api_version": api_version
        or _DEFAULTS["azure_openai_api_version"],
    }
    if api_key:
        values["azure_openai_api_key"] = api_key
    set_config_values(values)
    return get_azure_config(use_cache=False)


def get_server_options() -> dict[str, str]:
    return {
        "host": os.environ.get("APP_HOST", "127.0.0.1"),
        "port": os.environ.get("APP_PORT", "8000"),
    }
