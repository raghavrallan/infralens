"""Scale backends for org CLI executor pools (local Docker stub + Azure ACA)."""
from __future__ import annotations

import logging
import os
import shutil
import subprocess
from typing import Any, Protocol

logger = logging.getLogger(__name__)

PROVIDERS = ("azure", "aws", "github")


class ScaleBackend(Protocol):
    def scale_org(
        self,
        org_id: str,
        *,
        min_replicas: int,
        max_replicas: int,
        app_names: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Apply replica targets; return updated app name map."""


def _docker_available() -> bool:
    return shutil.which("docker") is not None


def local_container_name(org_id: str, provider: str) -> str:
    short = (org_id or "org").replace("-", "")[:12]
    return f"devsecops-{provider}-exec-{short}"


class LocalDockerScaler:
    """Start/stop compose-named or org-tagged local executor containers."""

    def scale_org(
        self,
        org_id: str,
        *,
        min_replicas: int,
        max_replicas: int,
        app_names: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        del max_replicas  # local stub is 0/1 per provider
        names = dict(app_names or {})
        if not _docker_available():
            # No Docker: record desired names and treat as soft success for tests.
            for provider in PROVIDERS:
                names.setdefault(provider, local_container_name(org_id, provider))
            logger.info(
                "Local scaler: docker unavailable; recorded desired state for org %s min=%s",
                org_id,
                min_replicas,
            )
            return names

        for provider in PROVIDERS:
            preferred = str(names.get(provider) or "").strip()
            candidates = [
                c
                for c in (
                    preferred,
                    local_container_name(org_id, provider),
                    f"devsecops-{provider}-executor",
                    f"devsecops-local-{provider}-executor",
                )
                if c
            ]
            chosen = None
            for name in candidates:
                if _container_exists(name):
                    chosen = name
                    break
            if chosen is None:
                names.setdefault(provider, candidates[0])
                continue
            names[provider] = chosen
            if min_replicas <= 0:
                _run(["docker", "stop", chosen], check=False)
            else:
                _run(["docker", "start", chosen], check=False)
        return names


class AzureContainerAppsScaler:
    """Scale Azure Container Apps via `az containerapp update` when configured."""

    def __init__(self) -> None:
        self.resource_group = os.environ.get("ACA_RESOURCE_GROUP", "").strip()
        self.environment = os.environ.get("ACA_ENVIRONMENT", "").strip()
        self.subscription = os.environ.get("AZURE_SUBSCRIPTION_ID", "").strip()
        self.image_prefix = os.environ.get(
            "ACA_EXECUTOR_IMAGE_PREFIX",
            "eqacrregistrydeveastus001.azurecr.io/devsecops-suite",
        ).rstrip("/")
        self.image_tag = os.environ.get("ACA_EXECUTOR_IMAGE_TAG", "latest").strip() or "latest"

    def enabled(self) -> bool:
        return bool(self.resource_group and shutil.which("az"))

    def scale_org(
        self,
        org_id: str,
        *,
        min_replicas: int,
        max_replicas: int,
        app_names: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if not self.enabled():
            raise RuntimeError(
                "Azure Container Apps scaler requires ACA_RESOURCE_GROUP and az CLI"
            )
        names = dict(app_names or {})
        max_r = max(1, int(max_replicas))
        min_r = max(0, min(int(min_replicas), max_r))
        for provider in PROVIDERS:
            app_name = str(names.get(provider) or "").strip() or _default_aca_name(org_id, provider)
            if not self._app_exists(app_name):
                self._create_app(org_id, provider, app_name)
            self._set_scale(app_name, min_r, max_r)
            names[provider] = app_name
        return names

    def _app_exists(self, app_name: str) -> bool:
        cmd = [
            "az",
            "containerapp",
            "show",
            "--name",
            app_name,
            "--resource-group",
            self.resource_group,
            "-o",
            "none",
        ]
        if self.subscription:
            cmd.extend(["--subscription", self.subscription])
        result = _run(cmd, check=False)
        return result.returncode == 0

    def _create_app(self, org_id: str, provider: str, app_name: str) -> None:
        if not self.environment:
            raise RuntimeError("ACA_ENVIRONMENT is required to provision executor apps")
        image = f"{self.image_prefix}-{provider}-executor:{self.image_tag}"
        redis_url = os.environ.get("REDIS_URL", "")
        control_plane = os.environ.get(
            "CONTROL_PLANE_INTERNAL_URL",
            os.environ.get("CONTROL_PLANE_URL", ""),
        )
        service_key = os.environ.get("EXECUTOR_SERVICE_KEY", "")
        env_vars = [
            f"REDIS_URL={redis_url}",
            f"CONTROL_PLANE_URL={control_plane}",
            f"EXECUTOR_SERVICE_KEY={service_key}",
            f"EXECUTOR_PROVIDER={provider}",
            f"EXECUTOR_ORG_ID={org_id}",
        ]
        cmd = [
            "az",
            "containerapp",
            "create",
            "--name",
            app_name,
            "--resource-group",
            self.resource_group,
            "--environment",
            self.environment,
            "--image",
            image,
            "--cpu",
            "0.5",
            "--memory",
            "1.0Gi",
            "--min-replicas",
            "0",
            "--max-replicas",
            "1",
            "--ingress",
            "internal",
            "--target-port",
            "8080",
            "--env-vars",
            *env_vars,
        ]
        if self.subscription:
            cmd.extend(["--subscription", self.subscription])
        _run(cmd, check=True)
        logger.info("Provisioned ACA executor app %s for org %s/%s", app_name, org_id, provider)

    def _set_scale(self, app_name: str, min_replicas: int, max_replicas: int) -> None:
        cmd = [
            "az",
            "containerapp",
            "update",
            "--name",
            app_name,
            "--resource-group",
            self.resource_group,
            "--min-replicas",
            str(min_replicas),
            "--max-replicas",
            str(max_replicas),
        ]
        if self.subscription:
            cmd.extend(["--subscription", self.subscription])
        _run(cmd, check=True)


def _default_aca_name(org_id: str, provider: str) -> str:
    short = (org_id or "org").replace("-", "")[:8].lower()
    return f"dss-{provider[:3]}-{short}"[:32]


def _container_exists(name: str) -> bool:
    result = _run(
        ["docker", "inspect", "-f", "{{.Id}}", name],
        check=False,
    )
    return result.returncode == 0 and bool((result.stdout or "").strip())


def _run(cmd: list[str], *, check: bool) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            cmd,
            check=check,
            capture_output=True,
            text=True,
            timeout=120,
        )
    except subprocess.CalledProcessError as exc:
        stderr = (exc.stderr or "")[:500]
        raise RuntimeError(f"Command failed ({' '.join(cmd[:4])}…): {stderr}") from exc
    except FileNotFoundError as exc:
        raise RuntimeError(f"Command not found: {cmd[0]}") from exc


def get_scaler() -> ScaleBackend:
    """Prefer Azure Container Apps when configured; otherwise local Docker stub."""
    aca = AzureContainerAppsScaler()
    backend = os.environ.get("ORG_EXECUTOR_SCALE_BACKEND", "").strip().lower()
    if backend == "aca" or (not backend and aca.enabled()):
        return aca
    return LocalDockerScaler()


def apply_scale(
    org_id: str,
    *,
    min_replicas: int,
    max_replicas: int,
    app_names: dict[str, Any] | None = None,
) -> dict[str, Any]:
    scaler = get_scaler()
    return scaler.scale_org(
        org_id,
        min_replicas=min_replicas,
        max_replicas=max_replicas,
        app_names=app_names,
    )


def scaler_kind() -> str:
    aca = AzureContainerAppsScaler()
    backend = os.environ.get("ORG_EXECUTOR_SCALE_BACKEND", "").strip().lower()
    if backend == "aca" or (not backend and aca.enabled()):
        return "aca"
    return "local"
