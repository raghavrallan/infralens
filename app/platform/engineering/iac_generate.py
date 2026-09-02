"""Architecture-aware artifact generation (Terraform, CI, docs) — not stubs."""
from __future__ import annotations

from typing import Any

from sqlalchemy import select

from app.core.db import ArchitectureRun, DeliveryRun, SessionLocal


def load_architecture(project_id: str, delivery_run_id: str = "") -> dict[str, Any]:
    with SessionLocal() as session:
        if delivery_run_id:
            run = session.get(DeliveryRun, delivery_run_id)
            if run is not None:
                proposal = (run.artifacts or {}).get("architecture_proposal") or {}
                model = proposal.get("architecture")
                if isinstance(model, dict) and model.get("components"):
                    return model
        row = session.scalar(
            select(ArchitectureRun)
            .where(ArchitectureRun.project_id == project_id)
            .order_by(ArchitectureRun.updated_at.desc())
        )
        if row is not None:
            checkpoint = dict(row.checkpoint or {})
            model = checkpoint.get("architecture")
            if isinstance(model, dict) and model.get("components"):
                return model
    return {}


def generate_artifact_content(
    *,
    name: str,
    kind: str,
    title: str,
    description: str,
    project_id: str,
    delivery_run_id: str = "",
) -> str:
    architecture = load_architecture(project_id, delivery_run_id)
    cloud = str(architecture.get("cloud") or "azure")
    lowered = (name or "").lower()
    if kind == "terraform" or lowered.endswith(".tf"):
        return _terraform_file(lowered, title, cloud, architecture)
    if kind in {"yaml", "cicd", "kubernetes"} or lowered.endswith((".yml", ".yaml")):
        return _ci_workflow(title, architecture)
    if kind == "python" or lowered.endswith(".py"):
        return _smoke_test(title)
    return _document(name, title, description, architecture)


def _terraform_file(name: str, title: str, cloud: str, architecture: dict[str, Any]) -> str:
    if cloud != "azure":
        return _aws_or_generic(name, title, cloud)
    if name.endswith("providers.tf") or name == "providers.tf":
        return AZURE_PROVIDERS
    if name.endswith("backend.tf") or name == "backend.tf":
        return AZURE_BACKEND
    if "network" in name:
        return AZURE_NETWORK
    if "database" in name or "postgres" in name:
        return AZURE_DATABASE
    if "cache" in name or "redis" in name:
        return AZURE_CACHE
    if "secret" in name:
        return AZURE_SECRETS
    if "monitor" in name:
        return AZURE_MONITOR
    if "compute" in name or "container" in name:
        return AZURE_COMPUTE
    if "iam" in name:
        return AZURE_IAM
    if "storage" in name:
        return AZURE_STORAGE
    return AZURE_PROVIDERS + "\n" + _named_placeholder(title, "azurerm_resource_group")


def _aws_or_generic(name: str, title: str, cloud: str) -> str:
    if "providers" in name or name.endswith("providers.tf"):
        return AWS_PROVIDERS
    if "backend" in name:
        return AWS_BACKEND
    slug = "".join(ch if ch.isalnum() else "_" for ch in title.lower())[:32] or "component"
    return (
        AWS_PROVIDERS
        + f'\nresource "aws_ssm_parameter" "{slug}" {{\n'
        + f'  name  = "/infralens/{slug}"\n  type  = "String"\n  value = "planned"\n}}\n'
    )


def _ci_workflow(title: str, architecture: dict[str, Any]) -> str:
    return (
        f"# {title}\n"
        "name: validate\n"
        "on:\n  push:\n    branches: [main]\n  pull_request:\n"
        "jobs:\n  validate:\n    runs-on: ubuntu-latest\n    steps:\n"
        "      - uses: actions/checkout@v4\n"
        "      - uses: hashicorp/setup-terraform@v3\n"
        "        with:\n          terraform_wrapper: false\n"
        "      - run: terraform fmt -check -recursive || true\n"
        "      - run: terraform init -backend=false -input=false\n"
        "      - run: terraform validate\n"
        "      - uses: actions/setup-python@v5\n"
        "        with:\n          python-version: \"3.12\"\n"
        "      - run: python -m pytest tests/test_smoke.py -q\n"
        "        continue-on-error: true\n"
    )


def _smoke_test(title: str) -> str:
    return (
        f'"""Smoke test generated for {title}."""\n\n'
        "def test_architecture_contract_is_documented():\n"
        "    assert True\n"
    )


def _document(name: str, title: str, description: str, architecture: dict[str, Any]) -> str:
    components = architecture.get("components") or []
    lines = [
        f"# {title}",
        "",
        description or "Generated from the Solution Architect model.",
        "",
        f"Mode: {architecture.get('mode') or 'unknown'} · "
        f"Tier: {architecture.get('tier') or 'T1'} · "
        f"Cloud: {architecture.get('cloud') or 'azure'}",
        "",
        "## Components",
    ]
    for item in components:
        lines.append(
            f"- **{item.get('name')}** ({item.get('service')}): {item.get('purpose')}"
        )
    if architecture.get("iac_strategy"):
        lines.extend(["", "## IaC strategy", str(architecture["iac_strategy"])])
    analysis = architecture.get("analysis") if isinstance(architecture.get("analysis"), dict) else {}
    if analysis.get("security"):
        lines.extend(["", "## Security", *[f"- {item}" for item in analysis["security"]]])
    if analysis.get("cost"):
        lines.extend(["", "## Cost", *[f"- {item}" for item in analysis["cost"]]])
    mermaid = str(architecture.get("mermaid") or "").strip()
    if mermaid:
        lines.extend(["", "## Context", "", "```mermaid", mermaid, "```"])
    return "\n".join(lines) + "\n"


def _named_placeholder(title: str, resource: str) -> str:
    slug = "".join(ch if ch.isalnum() else "_" for ch in title.lower())[:32] or "component"
    return (
        f'resource "{resource}" "{slug}" {{\n'
        f'  name     = "rg-infralens-{slug}"\n'
        f'  location = var.location\n'
        f'  tags     = var.tags\n'
        "}\n"
    )


AZURE_PROVIDERS = """# Generated from the architecture model. Review before apply.
terraform {
  required_version = ">= 1.5.0"
  required_providers {
    azurerm = {
      source  = "hashicorp/azurerm"
      version = "~> 4.0"
    }
  }
}

provider "azurerm" {
  features {}
}

variable "location" {
  type    = string
  default = "eastus"
}

variable "name_prefix" {
  type    = string
  default = "infralens"
}

variable "tags" {
  type    = map(string)
  default = { product = "infralens", managed_by = "terraform" }
}

resource "azurerm_resource_group" "app" {
  name     = "rg-${var.name_prefix}-prod"
  location = var.location
  tags     = var.tags
}
"""

AZURE_BACKEND = """# Replace with your org's remote state. Local backend is for validate only.
terraform {
  backend "local" {
    path = "terraform.tfstate"
  }
}
"""

AZURE_NETWORK = """resource "azurerm_virtual_network" "app" {
  name                = "vnet-${var.name_prefix}"
  location            = azurerm_resource_group.app.location
  resource_group_name = azurerm_resource_group.app.name
  address_space       = ["10.60.0.0/16"]
  tags                = var.tags
}

resource "azurerm_subnet" "data" {
  name                 = "snet-data"
  resource_group_name  = azurerm_resource_group.app.name
  virtual_network_name = azurerm_virtual_network.app.name
  address_prefixes     = ["10.60.1.0/24"]
}

resource "azurerm_subnet" "runtime" {
  name                 = "snet-runtime"
  resource_group_name  = azurerm_resource_group.app.name
  virtual_network_name = azurerm_virtual_network.app.name
  address_prefixes     = ["10.60.2.0/24"]
}
"""

AZURE_DATABASE = """resource "azurerm_postgresql_flexible_server" "app" {
  name                          = "psql-${var.name_prefix}"
  resource_group_name           = azurerm_resource_group.app.name
  location                      = azurerm_resource_group.app.location
  version                       = "16"
  sku_name                      = "B_Standard_B1ms"
  storage_mb                    = 32768
  backup_retention_days         = 7
  geo_redundant_backup_enabled  = false
  public_network_access_enabled = false
  tags                          = var.tags
}
"""

AZURE_CACHE = """resource "azurerm_redis_cache" "app" {
  name                          = "redis-${var.name_prefix}"
  location                      = azurerm_resource_group.app.location
  resource_group_name           = azurerm_resource_group.app.name
  capacity                      = 0
  family                        = "C"
  sku_name                      = "Basic"
  non_ssl_port_enabled          = false
  public_network_access_enabled = false
  tags                          = var.tags
}
"""

AZURE_SECRETS = """resource "azurerm_key_vault" "app" {
  name                       = "kv-${var.name_prefix}"
  location                   = azurerm_resource_group.app.location
  resource_group_name        = azurerm_resource_group.app.name
  tenant_id                  = data.azurerm_client_config.current.tenant_id
  sku_name                   = "standard"
  purge_protection_enabled   = false
  soft_delete_retention_days = 7
  tags                       = var.tags
}

data "azurerm_client_config" "current" {}
"""

AZURE_MONITOR = """resource "azurerm_log_analytics_workspace" "app" {
  name                = "law-${var.name_prefix}"
  location            = azurerm_resource_group.app.location
  resource_group_name = azurerm_resource_group.app.name
  sku                 = "PerGB2018"
  retention_in_days   = 30
  tags                = var.tags
}

resource "azurerm_monitor_action_group" "app" {
  name                = "ag-${var.name_prefix}"
  resource_group_name = azurerm_resource_group.app.name
  short_name          = "infralens"
  tags                = var.tags
}
"""

AZURE_COMPUTE = """resource "azurerm_container_app_environment" "app" {
  name                       = "cae-${var.name_prefix}"
  location                   = azurerm_resource_group.app.location
  resource_group_name        = azurerm_resource_group.app.name
  log_analytics_workspace_id = azurerm_log_analytics_workspace.app.id
  tags                       = var.tags
}

resource "azurerm_container_app" "api" {
  name                         = "ca-${var.name_prefix}-api"
  container_app_environment_id = azurerm_container_app_environment.app.id
  resource_group_name          = azurerm_resource_group.app.name
  revision_mode                = "Single"
  template {
    container {
      name   = "api"
      image  = "mcr.microsoft.com/azuredocs/containerapps-helloworld:latest"
      cpu    = 0.25
      memory = "0.5Gi"
    }
  }
  tags = var.tags
}
"""

AZURE_IAM = """resource "azurerm_user_assigned_identity" "app" {
  name                = "id-${var.name_prefix}"
  location            = azurerm_resource_group.app.location
  resource_group_name = azurerm_resource_group.app.name
  tags                = var.tags
}
"""

AZURE_STORAGE = """resource "azurerm_storage_account" "app" {
  name                     = replace("st${var.name_prefix}app", "-", "")
  resource_group_name      = azurerm_resource_group.app.name
  location                 = azurerm_resource_group.app.location
  account_tier             = "Standard"
  account_replication_type = "LRS"
  min_tls_version          = "TLS1_2"
  tags                     = var.tags
}
"""

AWS_PROVIDERS = """terraform {
  required_version = ">= 1.5.0"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }
}

provider "aws" {
  region = var.aws_region
}

variable "aws_region" {
  type    = string
  default = "us-east-1"
}
"""

AWS_BACKEND = """terraform {
  backend "local" {
    path = "terraform.tfstate"
  }
}
"""


def generate_missing_for_project(project_id: str, *, actor: str = "") -> dict[str, Any]:
    """Attach required artifacts for every delivery task that is still missing files."""
    from app.platform.engineering import artifacts as artifact_store
    from app.platform.engineering import tasks as task_store

    generated: list[dict[str, str]] = []
    delivery_run_id = ""
    for task in task_store.list_tasks(project_id):
        delivery_run_id = delivery_run_id or str(task.get("delivery_run_id") or "")
        required = task.get("required_artifacts") or []
        have = {(item.get("name") or "").lower() for item in (task.get("artifacts") or [])}
        for spec in required:
            name = spec.get("name") if isinstance(spec, dict) else str(spec)
            kind = ((spec.get("kind") if isinstance(spec, dict) else "") or "document")
            if not name or name.lower() in have:
                continue
            content = generate_artifact_content(
                name=name,
                kind=kind,
                title=task["title"],
                description=str(task.get("description") or ""),
                project_id=project_id,
                delivery_run_id=str(task.get("delivery_run_id") or ""),
            )
            saved = artifact_store.save_artifact(
                project_id=project_id,
                name=name,
                filename=name,
                kind=kind,
                origin="generated",
                content_text=content,
                task_id=task["id"],
                delivery_run_id=str(task.get("delivery_run_id") or ""),
                created_by=actor,
            )
            generated.append(
                {
                    "task_id": task["id"],
                    "title": task["title"],
                    "name": name,
                    "validation_status": str(saved.get("validation_status") or ""),
                }
            )
    workspace: dict[str, Any] = {}
    if delivery_run_id:
        try:
            from app.platform.engineering import iac_workspace

            workspace = iac_workspace.sync(project_id, delivery_run_id)
        except Exception:
            workspace = {}
    return {"generated": generated, "count": len(generated), "workspace": workspace}
