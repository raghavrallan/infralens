"""Project-isolated Terraform workspace on the control-plane disk."""
from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

from sqlalchemy import select

from app.core.db import ProjectArtifact, SessionLocal
from app.execution import terraform_runner
from app.platform import connections

_PUSHABLE = re.compile(r"\.(tf|md|yml|yaml|py)$", re.IGNORECASE)
_WORKSPACE_FILES = re.compile(r"\.(tf|md|yml|yaml)$", re.IGNORECASE)
_STRIP_ENV = ("ARM_", "AWS_", "AZURE_", "GH_TOKEN", "GITHUB_TOKEN")
_ISOLATED_LOCAL_BACKEND = """terraform {
  backend "local" {
    path = "terraform.tfstate"
  }
}
"""


def workspace_name(delivery_run_id: str) -> str:
    raw = (delivery_run_id or "default").strip()
    return raw[:80] if re.match(r"^[a-zA-Z0-9._-]+$", raw) else "default"


def load_generated_files(project_id: str, delivery_run_id: str = "") -> dict[str, str]:
    """Full artifact bodies (not the truncated list API)."""
    files: dict[str, str] = {}
    with SessionLocal() as session:
        stmt = select(ProjectArtifact).where(ProjectArtifact.project_id == project_id)
        if delivery_run_id:
            stmt = stmt.where(ProjectArtifact.delivery_run_id == delivery_run_id)
        rows = session.scalars(stmt).all()
        for row in rows:
            name = (row.filename or row.name or "").replace("\\", "/").lstrip("/")
            if not name or not _PUSHABLE.search(name):
                continue
            if ".." in name.split("/"):
                continue
            files[Path(name).name] = row.content_text or ""
    return files


def pin_isolated_backend(root: Path) -> Path:
    """Force local state on disk so isolated plan/apply never need a remote backend."""
    target = Path(root) / "backend.tf"
    target.write_text(_ISOLATED_LOCAL_BACKEND, encoding="utf-8")
    return target


def sync(project_id: str, delivery_run_id: str) -> dict[str, Any]:
    files = load_generated_files(project_id, delivery_run_id)
    if not files:
        raise ValueError("No generated Terraform/CI files to sync. Generate artifacts first.")
    name = workspace_name(delivery_run_id)
    terraform_files = {key: body for key, body in files.items() if _WORKSPACE_FILES.search(key)}
    root = terraform_runner.write_files(project_id, terraform_files or files, name)
    pin_isolated_backend(root)
    return {
        "workspace": str(root),
        "workspace_name": name,
        "project_id": project_id,
        "files": sorted(files.keys()),
        "file_count": len(files),
        "backend": "local",
    }


def project_cloud_env(project_id: str) -> dict[str, str]:
    """Host env minus foreign cloud tokens, plus this project's credentials only."""
    env = {
        key: value
        for key, value in os.environ.items()
        if not any(key.startswith(prefix) for prefix in _STRIP_ENV)
    }
    azure = connections.get_secret_fields(project_id, "azure") or {}
    if azure.get("client_id") and azure.get("client_secret") and azure.get("tenant_id"):
        env["ARM_CLIENT_ID"] = str(azure.get("client_id") or "")
        env["ARM_CLIENT_SECRET"] = str(azure.get("client_secret") or "")
        env["ARM_TENANT_ID"] = str(azure.get("tenant_id") or "")
        env["ARM_SUBSCRIPTION_ID"] = str(azure.get("subscription_id") or "")
    aws = connections.get_secret_fields(project_id, "aws") or {}
    if aws.get("access_key_id") and aws.get("secret_access_key"):
        env["AWS_ACCESS_KEY_ID"] = str(aws.get("access_key_id") or "")
        env["AWS_SECRET_ACCESS_KEY"] = str(aws.get("secret_access_key") or "")
        if aws.get("region"):
            env["AWS_DEFAULT_REGION"] = str(aws.get("region") or "")
    return env


def drop_plan_file(project_id: str, delivery_run_id: str) -> None:
    root = terraform_runner.workspace_dir(project_id, workspace_name(delivery_run_id))
    plan = root / "tfplan"
    if plan.exists():
        plan.unlink()


def run_phase(project_id: str, delivery_run_id: str, phase: str, *, auto_approve: bool = False) -> dict[str, Any]:
    name = workspace_name(delivery_run_id)
    terraform_runner.workspace_dir(project_id, name)
    return terraform_runner.run_local_phase(
        project_id,
        phase,
        name=name,
        auto_approve=auto_approve,
        env=project_cloud_env(project_id),
    )


def run_import(project_id: str, delivery_run_id: str, address: str, resource_id: str) -> dict[str, Any]:
    name = workspace_name(delivery_run_id)
    terraform_runner.workspace_dir(project_id, name)
    return terraform_runner.run_local_import(
        project_id,
        address,
        resource_id,
        name=name,
        env=project_cloud_env(project_id),
    )


def run_state_rm(project_id: str, delivery_run_id: str, address: str) -> dict[str, Any]:
    name = workspace_name(delivery_run_id)
    terraform_runner.workspace_dir(project_id, name)
    return terraform_runner.run_local_state_rm(
        project_id,
        address,
        name=name,
        env=project_cloud_env(project_id),
    )
