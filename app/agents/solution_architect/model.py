"""Typed architecture model built from discovery + architect state."""
from __future__ import annotations

from typing import Any


def build_architecture(state: dict[str, Any]) -> dict[str, Any]:
    discovery = dict(state.get("discovery") or {})
    cloud = str(discovery.get("cloud") or "azure")
    components = _components_from_state(state, discovery, cloud)
    return {
        "version": 1,
        "project_id": state.get("project_id") or "",
        "tier": state.get("tier") or "T1",
        "mode": state.get("mode") or "greenfield",
        "cloud": cloud,
        "stack": {
            "languages": discovery.get("languages") or [],
            "frameworks": discovery.get("frameworks") or [],
            "signals": discovery.get("signals") or [],
        },
        "inventory_summary": str(state.get("exploration_notes") or "")[:4000],
        "mermaid": state.get("mermaid") or "",
        "hld": state.get("hld") or state.get("reply") or "",
        "components": components,
        "decisions": [
            {
                "title": item.get("title") or "",
                "decision": item.get("decision") or item.get("change") or "",
                "reason": item.get("consequences") or item.get("context") or "",
                "gate": item.get("gate_decision") or item.get("gate") or "",
            }
            for item in (state.get("decisions") or [])
            if isinstance(item, dict)
        ],
        "iac_strategy": (
            "Terraform via PR, init → validate → plan, Lead+ gated apply. Never silent apply."
        ),
        "analysis": _analysis(cloud, discovery, state),
    }


def fallback_candidates(state: dict[str, Any]) -> list[dict[str, Any]]:
    """Replace the old 'managed queue' stub with discovery-backed options."""
    discovery = dict(state.get("discovery") or {})
    cloud = str(discovery.get("cloud") or "azure")
    compute = (
        "Azure Container Apps"
        if cloud == "azure"
        else "AWS ECS Fargate"
        if cloud == "aws"
        else "Cloud Run"
    )
    data = "Azure Database for PostgreSQL" if cloud == "azure" else "Managed PostgreSQL"
    return [
        {
            "pillar": "compute",
            "title": f"Managed containers on {compute}",
            "recommended": True,
            "change": f"Run the API and worker on {compute}; keep the frontend as a static site.",
            "risk_class": "config_code_change",
            "blast_radius": "medium",
            "options_considered": [
                {"name": compute, "tradeoffs": "Low ops, revision deploy, scale-to-zero"},
                {"name": "Kubernetes", "tradeoffs": "More control, much more ops"},
            ],
            "consequences": "Lower operational overhead than a cluster for a single product.",
            "justified": True,
        },
        {
            "pillar": "data_architecture",
            "title": f"Private {data} plus cache",
            "recommended": True,
            "change": f"Provision private {data} and Redis in a dedicated resource group.",
            "risk_class": "config_code_change",
            "blast_radius": "medium",
            "options_considered": [
                {"name": "Dedicated private data plane", "tradeoffs": "Isolation, extra cost"},
                {"name": "Reuse shared stores", "tradeoffs": "Cheaper, weaker isolation"},
            ],
            "consequences": "Production data is isolated and reversible via Terraform.",
            "justified": True,
        },
    ]


def _components_from_state(
    state: dict[str, Any], discovery: dict[str, Any], cloud: str
) -> list[dict[str, Any]]:
    signals = set(discovery.get("signals") or [])
    text = " ".join(
        [
            str(state.get("objective") or ""),
            str(state.get("hld") or ""),
            str(state.get("exploration_notes") or ""),
            " ".join(signals),
        ]
    ).lower()
    specs = [
        _comp(
            "repository",
            "requirements",
            "Repository setup",
            "Map source and document the delivery contract.",
            "github",
            "git",
            "README.md",
            "document",
            "",
        ),
        _comp(
            "iac",
            "infrastructure",
            "Terraform backend and providers",
            "Remote state and provider pin so plans are repeatable.",
            cloud,
            "terraform",
            "providers.tf",
            "terraform",
            "backend.tf",
        ),
        _comp(
            "networking",
            "infrastructure",
            "Network (VPC/VNet, subnets, routing)",
            "Private data-plane subnets and routing for the new workload.",
            cloud,
            "virtual_network" if cloud == "azure" else "vpc",
            "network.tf",
            "terraform",
            "",
        ),
        _comp(
            "compute",
            "infrastructure",
            "Compute platform",
            "Host the API and worker on a managed container platform.",
            cloud,
            "container_apps" if cloud == "azure" else "ecs",
            "compute.tf",
            "terraform",
            "",
        ),
        _comp(
            "database",
            "infrastructure",
            "Database and backups",
            "Managed PostgreSQL with backup retention.",
            cloud,
            "postgresql",
            "database.tf",
            "terraform",
            "",
        ),
        _comp(
            "cache",
            "infrastructure",
            "Cache layer",
            "Managed Redis for sessions and job coordination.",
            cloud,
            "redis",
            "cache.tf",
            "terraform",
            "",
        ),
        _comp(
            "secrets",
            "security",
            "Secret management",
            "Store app secrets in a managed vault, not env files.",
            cloud,
            "key_vault" if cloud == "azure" else "secrets_manager",
            "secrets.tf",
            "terraform",
            "",
        ),
        _comp(
            "iam",
            "security",
            "IAM / identity least privilege",
            "Workload identity for the runtime, no long-lived keys in the repo.",
            cloud,
            "managed_identity" if cloud == "azure" else "iam_role",
            "iam.tf",
            "terraform",
            "",
        ),
        _comp(
            "monitoring",
            "infrastructure",
            "Monitoring and alerting",
            "Logs, metrics, and an action group for incidents.",
            cloud,
            "monitor",
            "monitoring.tf",
            "terraform",
            "",
        ),
        _comp(
            "cicd",
            "cicd",
            "CI/CD with security scanning",
            "Validate IaC and application tests on every push.",
            "github",
            "actions",
            ".github/workflows/ci.yml",
            "cicd",
            "",
        ),
        _comp(
            "testing",
            "testing",
            "Integration tests",
            "Smoke tests that prove the generated contract still holds.",
            "github",
            "pytest",
            "tests/test_smoke.py",
            "python",
            "",
        ),
    ]
    always = {"repository", "iac"}
    wanted = set(always)
    if any(token in text for token in ("network", "vnet", "vpc", "private", "subnet", "aca", "container")):
        wanted.add("networking")
    if any(token in text for token in ("fastapi", "nextjs", "worker", "aca", "container", "compute", "api")):
        wanted.add("compute")
    if any(token in text for token in ("postgres", "database", "sql")):
        wanted.add("database")
    if "redis" in text or "cache" in text or "worker" in text:
        wanted.add("cache")
    if any(token in text for token in ("secret", "key vault", "vault", "keyvault")):
        wanted.add("secrets")
    if any(token in text for token in ("iam", "identity", "rbac", "least privilege")):
        wanted.add("iam")
    if any(token in text for token in ("monitor", "log analytics", "observab")):
        wanted.add("monitoring")
    if any(token in text for token in ("github_actions", "ci/cd", "workflow")):
        wanted.add("cicd")
    if any(token in text for token in ("test", "pytest")):
        wanted.add("testing")
    if len(wanted) <= 2:
        wanted.update({"networking", "compute", "database", "cache", "secrets", "iam", "monitoring", "cicd"})
    elif {"networking", "compute"} & wanted:
        wanted.update({"secrets", "iam", "monitoring"})
    return [item for item in specs if item["id"] in wanted]


def mermaid_from_discovery(state: dict[str, Any]) -> str:
    signals = set((state.get("discovery") or {}).get("signals") or [])
    text = f"{state.get('objective') or ''} {state.get('hld') or ''}".lower()
    frontend = "Next.js" if "nextjs" in signals else "React" if "react" in signals else "Frontend"
    api = "FastAPI" if "fastapi" in signals else "API"
    lines = [
        "flowchart LR",
        f"  users[Users] --> fe[{frontend}]",
        f"  fe --> api[{api}]",
    ]
    if "postgres" in signals or "database" in text:
        lines.append("  api --> db[(PostgreSQL)]")
    elif not signals:
        lines.append("  api --> db[(Data store)]")
    if "redis" in signals or "cache" in text:
        lines.append("  api --> cache[(Redis)]")
    if "worker" in signals:
        lines.append("  api --> worker[Worker]")
        if "postgres" in signals or not signals:
            lines.append("  worker --> db")
        if "redis" in signals:
            lines.append("  worker --> cache")
    return "\n".join(lines)


def _analysis(cloud: str, discovery: dict[str, Any], state: dict[str, Any]) -> dict[str, Any]:
    signals = set(discovery.get("signals") or [])
    compute = (
        "Azure Container Apps"
        if cloud == "azure"
        else "ECS Fargate"
        if cloud == "aws"
        else "Cloud Run"
    )
    return {
        "security": [
            "Private data-plane subnets; no public PostgreSQL or Redis.",
            "Secrets in a managed vault, never committed env files.",
            "Workload identity instead of static cloud keys.",
        ],
        "scaling": [
            f"{compute} scales replicas from HTTP/queue load; start with 0–3 replicas.",
            "Database vertical SKU first; add read replica only if read-heavy.",
        ],
        "cost": [
            f"Prefer {compute} over Kubernetes until multi-team cluster ops are justified.",
            "Basic Redis and burstable Postgres for moderate traffic; review after first month.",
        ],
        "availability": [
            "Single region with automated backups (7-day retention) unless the ask is multi-region.",
            "Revision-based deploys so a bad image can be rolled back without a cluster rebuild.",
        ],
        "brownfield": (
            "Extend the existing estate with a dedicated resource group; do not replace live apps."
            if state.get("mode") == "brownfield"
            else "Greenfield: provision a dedicated resource group and new data plane."
        ),
        "stack": sorted(signals),
    }


def _comp(
    ident: str,
    stage: str,
    name: str,
    purpose: str,
    provider: str,
    service: str,
    filename: str,
    kind: str,
    extra_file: str,
) -> dict[str, Any]:
    artifacts = [{"name": filename, "kind": kind}]
    if extra_file:
        artifacts.append({"name": extra_file, "kind": kind})
    return {
        "id": ident,
        "pillar": ident,
        "stage": stage,
        "name": name,
        "purpose": purpose,
        "provider": provider,
        "service": service,
        "reason": purpose,
        "alternatives": [],
        "dependencies": _component_deps(ident),
        "security_considerations": _component_security(ident),
        "scaling_strategy": _component_scaling(ident),
        "availability_strategy": _component_availability(ident),
        "cost_considerations": _component_cost(ident),
        "artifact": artifacts[0],
        "artifacts": artifacts,
        "implementation_status": "proposed",
        "validation_status": "pending",
        "status": "proposed",
    }


def _component_deps(ident: str) -> list[str]:
    return {
        "compute": ["networking", "secrets", "iam", "monitoring"],
        "database": ["networking", "secrets"],
        "cache": ["networking", "secrets"],
        "secrets": ["iam"],
        "monitoring": [],
        "cicd": ["iac"],
        "testing": ["cicd"],
    }.get(ident, [])


def _component_security(ident: str) -> str:
    return {
        "networking": "Private subnets for data; no public IPs on stores.",
        "compute": "HTTPS ingress only; no privileged containers.",
        "database": "Private access, TLS, backup encryption at rest.",
        "cache": "TLS only; no non-SSL port.",
        "secrets": "Purge protection off for lab, on for prod; RBAC not access policies.",
        "iam": "Least-privilege managed identity; no subscription Owner on the app.",
        "cicd": "OIDC to cloud; no long-lived secrets in GitHub.",
    }.get(ident, "Follow the project baseline.")


def _component_scaling(ident: str) -> str:
    return {
        "compute": "HTTP concurrency autoscaling, min 0 in non-prod, min 1 in prod.",
        "database": "Start burstable; add storage before CPU.",
        "cache": "Basic SKU until cache-hit data justifies Standard.",
    }.get(ident, "Scale with the compute tier.")


def _component_availability(ident: str) -> str:
    return {
        "compute": "Revision rollback; multi-replica once traffic is steady.",
        "database": "7-day backups; geo-redundant only if the ask is multi-region.",
        "cache": "Treat as ephemeral; app must tolerate flush.",
    }.get(ident, "Match the compute region's availability.")


def _component_cost(ident: str) -> str:
    return {
        "compute": "Lower ops cost than AKS/EKS for a single product.",
        "database": "Burstable SKU until utilization is measured.",
        "cache": "Basic C0 until session/job volume requires more.",
        "monitoring": "30-day Log Analytics; cap daily ingest in prod.",
    }.get(ident, "Review after the first plan.")
