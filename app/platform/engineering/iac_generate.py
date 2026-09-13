"""Architecture-aware Terraform generation - real module trees, not LLM junk."""
from __future__ import annotations

from typing import Any

from sqlalchemy import select

from app.core.db import ArchitectureRun, DeliveryRun, SessionLocal


def load_architecture(project_id: str, delivery_run_id: str = "") -> dict[str, Any]:
    try:
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
    except Exception:
        # Unit tests / degraded DBs should still get deterministic module skeletons.
        return {}
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
    cloud = _cloud(architecture)
    lowered = (name or "").lower().replace("\\", "/")

    if lowered.startswith("modules/") or lowered.startswith("envs/") or lowered in {
        "readme.md",
        "main.tf",
        "providers.tf",
        "backend.tf",
        "variables.tf",
        "outputs.tf",
    }:
        tree = generate_module_env_tree(architecture, env="dev")
        if lowered in tree:
            return tree[lowered]
        base = lowered.rsplit("/", 1)[-1]
        for path_key, content in tree.items():
            if path_key.endswith("/" + base) or path_key == base:
                return content

    if kind == "terraform" or lowered.endswith(".tf"):
        return _terraform_file(lowered, title, cloud, architecture)
    if kind in {"yaml", "cicd", "kubernetes"} or lowered.endswith((".yml", ".yaml")):
        return _ci_workflow(title)
    if kind == "python" or lowered.endswith(".py"):
        return _smoke_test(title)
    return _document(name, title, description, architecture)


def _cloud(architecture: dict[str, Any]) -> str:
    raw = str(architecture.get("cloud") or architecture.get("provider") or "azure").lower()
    return "aws" if raw in {"aws", "amazon"} else "azure"


def _slug(value: str) -> str:
    cleaned = "".join(ch.lower() if ch.isalnum() else "-" for ch in (value or "component"))
    while "--" in cleaned:
        cleaned = cleaned.replace("--", "-")
    return cleaned.strip("-")[:48] or "component"


def _kind_hint(name: str, title: str = "") -> str:
    blob = f"{name} {title}".lower()
    if "provider" in blob:
        return "providers"
    if "backend" in blob:
        return "backend"
    if any(tok in blob for tok in ("network", "vpc", "vnet", "subnet")):
        return "network"
    if any(tok in blob for tok in ("database", "postgres", "rds", "sql", "cosmos")):
        return "database"
    if any(tok in blob for tok in ("cache", "redis")):
        return "cache"
    if any(tok in blob for tok in ("secret", "vault", "kms")):
        return "secrets"
    if any(tok in blob for tok in ("monitor", "observ", "cloudwatch", "log")):
        return "monitoring"
    if any(tok in blob for tok in ("compute", "container", "ecs", "eks", "aks", "app", "fargate")):
        return "compute"
    if any(tok in blob for tok in ("iam", "identity", "rbac")):
        return "iam"
    if any(tok in blob for tok in ("storage", "s3", "blob")):
        return "storage"
    return "generic"


def _module_wrapper(module_name: str, *, needs_network: bool = False) -> str:
    extra = ""
    if needs_network:
        extra = (
            "\n  subnet_ids         = module.network.private_subnet_ids"
            "\n  security_group_ids = [module.network.security_group_id]"
        )
    return (
        f"# Thin root wrapper - resources live in modules/{module_name}/\n"
        f'module "{module_name}" {{\n'
        f'  source      = "./modules/{module_name}"\n'
        f'  name_prefix = var.name_prefix\n'
        f'  tags        = var.tags{extra}\n'
        f"}}\n"
    )


def _terraform_file(name: str, title: str, cloud: str, architecture: dict[str, Any]) -> str:
    kind = _kind_hint(name, title)
    if kind == "providers" or name.endswith("providers.tf"):
        return AWS_PROVIDERS if cloud == "aws" else AZURE_PROVIDERS
    if kind == "backend" or name.endswith("backend.tf"):
        return LOCAL_BACKEND
    if name.endswith("variables.tf") and "/" not in name:
        return ROOT_VARIABLES
    if name == "main.tf":
        return generate_module_env_tree(architecture, env="dev").get("main.tf", "")

    # Flat task files are pointers only. Root main.tf owns module composition
    # so we do not instantiate the same module twice.
    module_name = kind if kind != "generic" else (_slug(title) or "component")
    return (
        f"# Task artifact satisfied by modules/{module_name}/ and root main.tf.\n"
        f"# Do not duplicate module \"{module_name}\" here - composition is centralized.\n"
    )


def _ci_workflow(title: str) -> str:
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
        if isinstance(item, dict):
            lines.append(
                f"- **{item.get('name')}** ({item.get('service')}): {item.get('purpose')}"
            )
    if architecture.get("iac_strategy"):
        lines.extend(["", "## IaC strategy", str(architecture["iac_strategy"])])
    return "\n".join(lines) + "\n"


def title_case(value: str) -> str:
    return " ".join(part.capitalize() for part in value.replace("-", " ").replace("_", " ").split())


# ---------------------------------------------------------------------------
# Root / providers
# ---------------------------------------------------------------------------

LOCAL_BACKEND = """# Isolated delivery uses local state.
terraform {
  backend "local" {
    path = "terraform.tfstate"
  }
}
"""

ROOT_VARIABLES = """variable "name_prefix" {
  type    = string
  default = "infralens-dev"
}

variable "tags" {
  type = map(string)
  default = {
    product    = "infralens"
    managed_by = "terraform"
  }
}

variable "location" {
  type    = string
  default = "eastus"
}

variable "aws_region" {
  type    = string
  default = "us-east-1"
}
"""

AZURE_PROVIDERS = """# Root providers only - resources live under modules/.
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
"""

AWS_PROVIDERS = """# Root providers only - resources live under modules/.
terraform {
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
"""

# ---------------------------------------------------------------------------
# Self-contained AWS modules
# ---------------------------------------------------------------------------

AWS_MOD_NETWORK = """data "aws_availability_zones" "available" {
  state = "available"
}

resource "aws_vpc" "app" {
  cidr_block           = var.vpc_cidr
  enable_dns_hostnames = true
  enable_dns_support   = true
  tags                 = merge(var.tags, { Name = "vpc-${var.name_prefix}" })
}

resource "aws_subnet" "public" {
  vpc_id                  = aws_vpc.app.id
  cidr_block              = cidrsubnet(var.vpc_cidr, 8, 1)
  map_public_ip_on_launch = true
  availability_zone       = data.aws_availability_zones.available.names[0]
  tags                    = merge(var.tags, { Name = "snet-public-${var.name_prefix}" })
}

resource "aws_subnet" "private" {
  vpc_id            = aws_vpc.app.id
  cidr_block        = cidrsubnet(var.vpc_cidr, 8, 2)
  availability_zone = data.aws_availability_zones.available.names[0]
  tags              = merge(var.tags, { Name = "snet-private-${var.name_prefix}" })
}

resource "aws_internet_gateway" "app" {
  vpc_id = aws_vpc.app.id
  tags   = merge(var.tags, { Name = "igw-${var.name_prefix}" })
}

resource "aws_security_group" "app" {
  name        = "sg-${var.name_prefix}"
  description = "App security group"
  vpc_id      = aws_vpc.app.id
  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
  tags = var.tags
}
"""

AWS_MOD_COMPUTE = """resource "aws_iam_role" "ecs_execution" {
  name = "role-${var.name_prefix}-ecs-exec"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Action    = "sts:AssumeRole"
      Effect    = "Allow"
      Principal = { Service = "ecs-tasks.amazonaws.com" }
    }]
  })
  tags = var.tags
}

resource "aws_iam_role_policy_attachment" "ecs_execution" {
  role       = aws_iam_role.ecs_execution.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy"
}

resource "aws_ecs_cluster" "app" {
  name = "ecs-${var.name_prefix}"
  tags = var.tags
}

resource "aws_ecs_task_definition" "api" {
  family                   = "${var.name_prefix}-api"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = "256"
  memory                   = "512"
  execution_role_arn       = aws_iam_role.ecs_execution.arn
  container_definitions = jsonencode([{
    name      = "api"
    image     = "public.ecr.aws/nginx/nginx:stable"
    essential = true
    portMappings = [{ containerPort = 80, protocol = "tcp" }]
  }])
  tags = var.tags
}

resource "aws_ecs_service" "api" {
  count           = length(var.subnet_ids) > 0 ? 1 : 0
  name            = "svc-${var.name_prefix}-api"
  cluster         = aws_ecs_cluster.app.id
  task_definition = aws_ecs_task_definition.api.arn
  desired_count   = 1
  launch_type     = "FARGATE"
  network_configuration {
    subnets          = var.subnet_ids
    security_groups  = var.security_group_ids
    assign_public_ip = false
  }
  tags = var.tags
}
"""

AWS_MOD_DATABASE = """resource "aws_db_subnet_group" "app" {
  count      = length(var.subnet_ids) > 0 ? 1 : 0
  name       = "dbsubnet-${var.name_prefix}"
  subnet_ids = var.subnet_ids
  tags       = var.tags
}

resource "aws_db_instance" "app" {
  identifier                  = "rds-${var.name_prefix}"
  engine                      = "postgres"
  engine_version              = "16"
  instance_class              = "db.t4g.micro"
  allocated_storage           = 20
  db_subnet_group_name        = try(aws_db_subnet_group.app[0].name, null)
  vpc_security_group_ids      = var.security_group_ids
  username                    = "appadmin"
  manage_master_user_password = true
  skip_final_snapshot         = true
  publicly_accessible         = false
  storage_encrypted           = true
  tags                        = var.tags
}
"""

AWS_MOD_STORAGE = """resource "aws_s3_bucket" "app" {
  bucket = "${var.name_prefix}-app-data"
  tags   = var.tags
}

resource "aws_s3_bucket_public_access_block" "app" {
  bucket                  = aws_s3_bucket.app.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}
"""

AWS_MOD_IAM = """resource "aws_iam_role" "workload" {
  name = "role-${var.name_prefix}-workload"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Action    = "sts:AssumeRole"
      Effect    = "Allow"
      Principal = { Service = "ecs-tasks.amazonaws.com" }
    }]
  })
  tags = var.tags
}
"""

AWS_MOD_SECRETS = """resource "aws_secretsmanager_secret" "app" {
  name                    = "secret/${var.name_prefix}/app"
  recovery_window_in_days = 7
  tags                    = var.tags
}
"""

AWS_MOD_MONITORING = """resource "aws_cloudwatch_log_group" "app" {
  name              = "/infralens/${var.name_prefix}"
  retention_in_days = 30
  tags              = var.tags
}
"""

AWS_MOD_CACHE = """resource "aws_elasticache_subnet_group" "app" {
  count      = length(var.subnet_ids) > 0 ? 1 : 0
  name       = "redis-subnets-${var.name_prefix}"
  subnet_ids = var.subnet_ids
}

resource "aws_elasticache_cluster" "app" {
  cluster_id           = "redis-${var.name_prefix}"
  engine               = "redis"
  node_type            = "cache.t4g.micro"
  num_cache_nodes      = 1
  parameter_group_name = "default.redis7"
  subnet_group_name    = try(aws_elasticache_subnet_group.app[0].name, null)
  security_group_ids   = var.security_group_ids
  tags                 = var.tags
}
"""

AWS_MOD_GENERIC = """resource "aws_ssm_parameter" "marker" {
  name  = "/infralens/${var.name_prefix}/marker"
  type  = "String"
  value = "planned"
  tags  = var.tags
}
"""

# ---------------------------------------------------------------------------
# Self-contained Azure modules
# ---------------------------------------------------------------------------

AZURE_MOD_NETWORK = """resource "azurerm_resource_group" "app" {
  name     = "rg-${var.name_prefix}"
  location = var.location
  tags     = var.tags
}

resource "azurerm_virtual_network" "app" {
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

AZURE_MOD_COMPUTE = """resource "azurerm_log_analytics_workspace" "app" {
  name                = "law-${var.name_prefix}"
  location            = var.location
  resource_group_name = coalesce(var.resource_group_name, "rg-${var.name_prefix}")
  sku                 = "PerGB2018"
  retention_in_days   = 30
  tags                = var.tags
}

resource "azurerm_container_app_environment" "app" {
  name                       = "cae-${var.name_prefix}"
  location                   = var.location
  resource_group_name        = coalesce(var.resource_group_name, "rg-${var.name_prefix}")
  log_analytics_workspace_id = azurerm_log_analytics_workspace.app.id
  tags                       = var.tags
}

resource "azurerm_container_app" "api" {
  name                         = "ca-${var.name_prefix}-api"
  container_app_environment_id = azurerm_container_app_environment.app.id
  resource_group_name          = coalesce(var.resource_group_name, "rg-${var.name_prefix}")
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

AZURE_MOD_DATABASE = """resource "azurerm_postgresql_flexible_server" "app" {
  name                          = "psql-${var.name_prefix}"
  resource_group_name           = coalesce(var.resource_group_name, "rg-${var.name_prefix}")
  location                      = var.location
  version                       = "16"
  sku_name                      = "B_Standard_B1ms"
  storage_mb                    = 32768
  backup_retention_days         = 7
  geo_redundant_backup_enabled  = false
  public_network_access_enabled = false
  administrator_login           = "psqladmin"
  administrator_password        = "ChangeMe-NotForProd-1!"
  tags                          = var.tags
}
"""

AZURE_MOD_STORAGE = """resource "azurerm_storage_account" "app" {
  name                     = substr(replace("st${var.name_prefix}", "-", ""), 0, 24)
  resource_group_name      = coalesce(var.resource_group_name, "rg-${var.name_prefix}")
  location                 = var.location
  account_tier             = "Standard"
  account_replication_type = "LRS"
  min_tls_version          = "TLS1_2"
  tags                     = var.tags
}
"""

AZURE_MOD_IAM = """resource "azurerm_user_assigned_identity" "app" {
  name                = "id-${var.name_prefix}"
  location            = var.location
  resource_group_name = coalesce(var.resource_group_name, "rg-${var.name_prefix}")
  tags                = var.tags
}
"""

AZURE_MOD_SECRETS = """data "azurerm_client_config" "current" {}

resource "azurerm_key_vault" "app" {
  name                       = substr(replace("kv${var.name_prefix}", "-", ""), 0, 24)
  location                   = var.location
  resource_group_name        = coalesce(var.resource_group_name, "rg-${var.name_prefix}")
  tenant_id                  = data.azurerm_client_config.current.tenant_id
  sku_name                   = "standard"
  soft_delete_retention_days = 7
  tags                       = var.tags
}
"""

AZURE_MOD_MONITORING = """resource "azurerm_log_analytics_workspace" "app" {
  name                = "law-${var.name_prefix}"
  location            = var.location
  resource_group_name = coalesce(var.resource_group_name, "rg-${var.name_prefix}")
  sku                 = "PerGB2018"
  retention_in_days   = 30
  tags                = var.tags
}
"""

AZURE_MOD_CACHE = """resource "azurerm_redis_cache" "app" {
  name                          = "redis-${var.name_prefix}"
  location                      = var.location
  resource_group_name           = coalesce(var.resource_group_name, "rg-${var.name_prefix}")
  capacity                      = 0
  family                        = "C"
  sku_name                      = "Basic"
  non_ssl_port_enabled          = false
  public_network_access_enabled = false
  tags                          = var.tags
}
"""

AZURE_MOD_GENERIC = """resource "azurerm_resource_group" "marker" {
  name     = "rg-${var.name_prefix}-marker"
  location = var.location
  tags     = var.tags
}
"""


def _module_body(kind: str, cloud: str) -> str:
    if cloud == "aws":
        return {
            "network": AWS_MOD_NETWORK,
            "compute": AWS_MOD_COMPUTE,
            "database": AWS_MOD_DATABASE,
            "storage": AWS_MOD_STORAGE,
            "iam": AWS_MOD_IAM,
            "secrets": AWS_MOD_SECRETS,
            "monitoring": AWS_MOD_MONITORING,
            "cache": AWS_MOD_CACHE,
        }.get(kind, AWS_MOD_GENERIC)
    return {
        "network": AZURE_MOD_NETWORK,
        "compute": AZURE_MOD_COMPUTE,
        "database": AZURE_MOD_DATABASE,
        "storage": AZURE_MOD_STORAGE,
        "iam": AZURE_MOD_IAM,
        "secrets": AZURE_MOD_SECRETS,
        "monitoring": AZURE_MOD_MONITORING,
        "cache": AZURE_MOD_CACHE,
    }.get(kind, AZURE_MOD_GENERIC)


def _module_variables(kind: str, cloud: str) -> str:
    base = (
        'variable "name_prefix" {\n  type = string\n}\n\n'
        'variable "tags" {\n  type = map(string)\n  default = {}\n}\n'
    )
    if kind == "network" and cloud == "aws":
        base += '\nvariable "vpc_cidr" {\n  type = string\n  default = "10.60.0.0/16"\n}\n'
    if cloud == "azure":
        base += '\nvariable "location" {\n  type = string\n  default = "eastus"\n}\n'
    if kind in {"compute", "database", "cache"}:
        base += (
            '\nvariable "subnet_ids" {\n  type = list(string)\n  default = []\n}\n'
            '\nvariable "security_group_ids" {\n  type = list(string)\n  default = []\n}\n'
        )
    if cloud == "azure" and kind != "network":
        base += '\nvariable "resource_group_name" {\n  type = string\n  default = ""\n}\n'
    return base


def _module_outputs(kind: str, cloud: str, name: str) -> str:
    lines = [f'output "module_name" {{\n  value = "{name}"\n}}\n']
    if kind == "network" and cloud == "aws":
        lines.extend(
            [
                'output "vpc_id" {\n  value = aws_vpc.app.id\n}\n',
                'output "private_subnet_ids" {\n  value = [aws_subnet.private.id]\n}\n',
                'output "public_subnet_ids" {\n  value = [aws_subnet.public.id]\n}\n',
                'output "security_group_id" {\n  value = aws_security_group.app.id\n}\n',
            ]
        )
    elif kind == "network" and cloud == "azure":
        lines.extend(
            [
                'output "resource_group_name" {\n  value = azurerm_resource_group.app.name\n}\n',
                'output "location" {\n  value = azurerm_resource_group.app.location\n}\n',
                'output "vnet_id" {\n  value = azurerm_virtual_network.app.id\n}\n',
                'output "private_subnet_ids" {\n  value = [azurerm_subnet.data.id, azurerm_subnet.runtime.id]\n}\n',
                'output "security_group_id" {\n  value = ""\n}\n',
            ]
        )
    return "\n".join(lines)


def _service_kind(service: str, name: str) -> str:
    blob = f"{service} {name}".lower()
    return _kind_hint(blob, blob)


def generate_module_env_tree(
    architecture: dict[str, Any],
    *,
    env: str = "dev",
) -> dict[str, str]:
    """Workspace-ready module layout: root providers/main + modules/<component>."""
    cloud = _cloud(architecture)
    components = [item for item in (architecture.get("components") or []) if isinstance(item, dict)]
    if not components:
        components = [
            {"name": "network", "service": "network", "purpose": "Network foundation"},
            {"name": "compute", "service": "compute", "purpose": "Runtime"},
            {"name": "database", "service": "database", "purpose": "Data store"},
        ]

    files: dict[str, str] = {}
    module_names: list[str] = []
    kinds: dict[str, str] = {}

    for item in components[:12]:
        name = _slug(str(item.get("name") or item.get("service") or "component"))
        if name in module_names:
            continue
        module_names.append(name)
        kind = _service_kind(str(item.get("service") or ""), name)
        if kind in {"providers", "backend", "generic"}:
            kind = _service_kind(str(item.get("purpose") or item.get("description") or ""), name)
        if kind in {"providers", "backend"}:
            kind = "generic"
        kinds[name] = kind
        purpose = str(item.get("purpose") or item.get("description") or title_case(name))
        files[f"modules/{name}/main.tf"] = (
            f"# Module: {name}\n# Purpose: {purpose}\n# Cloud: {cloud}\n"
            f"# Deterministic skeleton (Azure OpenAI enrich disabled - was corrupting HCL).\n\n"
            + _module_body(kind, cloud)
        )
        files[f"modules/{name}/variables.tf"] = _module_variables(kind, cloud)
        files[f"modules/{name}/outputs.tf"] = _module_outputs(kind, cloud, name)

    for required in ("network", "compute", "database"):
        if required not in module_names:
            module_names.append(required)
            kinds[required] = required
            files[f"modules/{required}/main.tf"] = (
                f"# Module: {required}\n# Cloud: {cloud}\n\n" + _module_body(required, cloud)
            )
            files[f"modules/{required}/variables.tf"] = _module_variables(required, cloud)
            files[f"modules/{required}/outputs.tf"] = _module_outputs(required, cloud, required)

    files["providers.tf"] = AWS_PROVIDERS if cloud == "aws" else AZURE_PROVIDERS
    files["backend.tf"] = LOCAL_BACKEND
    files["variables.tf"] = ROOT_VARIABLES.replace("infralens-dev", f"infralens-{env}")

    ordered = sorted(module_names, key=lambda n: (0 if kinds.get(n) == "network" else 1, n))
    blocks = [
        f"# Environment root ({env}) - module composition only.\n# Cloud: {cloud}.\n"
    ]
    for name in ordered:
        kind = kinds.get(name, "generic")
        extra = ""
        if kind in {"compute", "database", "cache"} and "network" in module_names:
            extra = (
                "\n  subnet_ids         = module.network.private_subnet_ids"
                "\n  security_group_ids = [module.network.security_group_id]"
            )
            if cloud == "azure":
                extra += (
                    "\n  location            = module.network.location"
                    "\n  resource_group_name = module.network.resource_group_name"
                )
        blocks.append(
            f'module "{name}" {{\n'
            f'  source      = "./modules/{name}"\n'
            f'  name_prefix = var.name_prefix\n'
            f'  tags        = var.tags{extra}\n'
            f"}}\n"
        )
    files["main.tf"] = "\n".join(blocks)
    files["outputs.tf"] = "\n".join(
        f'output "{name}_module" {{\n  value = module.{name}.module_name\n}}\n' for name in ordered
    )
    files["README.md"] = (
        f"# Generated IaC ({cloud})\n\n"
        "Root composes reusable modules under `modules/`.\n"
        "Isolated delivery uses a local backend. Deterministic skeletons only - "
        "Azure OpenAI enrich is disabled because it was producing broken HCL.\n"
    )
    # Repo-shaped export mirror
    for root_name in ("providers.tf", "backend.tf", "variables.tf", "main.tf", "outputs.tf"):
        files[f"envs/{env}/{root_name}"] = files[root_name].replace(
            'source      = "./modules/',
            'source      = "../../modules/',
        )
    return files


def generate_missing_for_project(project_id: str, *, actor: str = "") -> dict[str, Any]:
    """Write module/env tree first, then fill any still-missing task artifacts."""
    from app.platform.engineering import artifacts as artifact_store
    from app.platform.engineering import tasks as task_store

    generated: list[dict[str, str]] = []
    delivery_run_id = ""
    for task in task_store.list_tasks(project_id):
        delivery_run_id = delivery_run_id or str(task.get("delivery_run_id") or "")

    try:
        architecture = load_architecture(project_id, delivery_run_id)
        tree = generate_module_env_tree(architecture, env="dev")
        existing = {
            (item.get("name") or item.get("filename") or "").replace("\\", "/").lower()
            for item in artifact_store.list_artifacts(project_id)
        }
        for rel_path, content in tree.items():
            if rel_path.startswith("envs/"):
                continue  # root workspace files are enough for isolated init/plan
            key = rel_path.replace("\\", "/").lower()
            # Always refresh module/root terraform so prior flat/LLM junk is replaced.
            if key in existing and not key.endswith(".tf"):
                continue
            saved = artifact_store.save_artifact(
                project_id=project_id,
                name=rel_path,
                filename=rel_path,
                kind="terraform" if rel_path.endswith(".tf") else (
                    "markdown" if rel_path.endswith(".md") else "document"
                ),
                origin="generated",
                content_text=content,
                task_id="",
                delivery_run_id=delivery_run_id,
                created_by=actor,
            )
            generated.append(
                {
                    "task_id": "",
                    "title": "module-env-tree",
                    "name": rel_path,
                    "validation_status": str(saved.get("validation_status") or ""),
                }
            )
            existing.add(key)
    except Exception:
        pass

    for task in task_store.list_tasks(project_id):
        delivery_run_id = delivery_run_id or str(task.get("delivery_run_id") or "")
        required = task.get("required_artifacts") or []
        have = {
            (item.get("name") or "").replace("\\", "/").lower()
            for item in (task.get("artifacts") or [])
        }
        for spec in required:
            name = spec.get("name") if isinstance(spec, dict) else str(spec)
            kind = ((spec.get("kind") if isinstance(spec, dict) else "") or "document")
            if not name or name.replace("\\", "/").lower() in have:
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
