"""Turn architecture output into requirements, tasks, and risks."""
from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select

from app.core.db import DeliveryRun, ProjectRequirement, SessionLocal
from app.platform.engineering import activity, knowledge, tasks as task_store

CATALOG: list[dict[str, Any]] = [
    {
        "keys": ("repo", "github", "repository"),
        "title": "Repository setup",
        "stage": "requirements",
        "artifacts": [{"name": "README.md", "kind": "document"}],
        "rules": [],
    },
    {
        "keys": ("terraform", "iac", "bicep"),
        "title": "Terraform backend and providers",
        "stage": "infrastructure",
        "artifacts": [{"name": "providers.tf", "kind": "terraform"}, {"name": "backend.tf", "kind": "terraform"}],
        "rules": ["terraform"],
    },
    {
        "keys": ("vpc", "vnet", "subnet", "network"),
        "title": "Network (VPC/VNet, subnets, routing)",
        "stage": "infrastructure",
        "artifacts": [{"name": "network.tf", "kind": "terraform"}],
        "rules": ["terraform"],
    },
    {
        "keys": ("iam", "rbac", "identity"),
        "title": "IAM / identity least privilege",
        "stage": "security",
        "artifacts": [{"name": "iam.tf", "kind": "terraform"}],
        "rules": ["terraform"],
    },
    {
        "keys": ("eks", "ecs", "aks", "kubernetes", "k8s"),
        "title": "Compute platform (cluster / services)",
        "stage": "infrastructure",
        "artifacts": [{"name": "compute.tf", "kind": "terraform"}],
        "rules": ["terraform"],
    },
    {
        "keys": ("rds", "aurora", "postgres", "database", "sql"),
        "title": "Database and backups",
        "stage": "infrastructure",
        "artifacts": [{"name": "database.tf", "kind": "terraform"}],
        "rules": ["terraform"],
    },
    {
        "keys": ("redis", "elasticache", "cache"),
        "title": "Cache layer",
        "stage": "infrastructure",
        "artifacts": [{"name": "cache.tf", "kind": "terraform"}],
        "rules": ["terraform"],
    },
    {
        "keys": ("s3", "blob", "object storage"),
        "title": "Object storage",
        "stage": "infrastructure",
        "artifacts": [{"name": "storage.tf", "kind": "terraform"}],
        "rules": ["terraform"],
    },
    {
        "keys": ("cloudfront", "cdn", "waf"),
        "title": "Edge / WAF / CDN",
        "stage": "security",
        "artifacts": [{"name": "edge.tf", "kind": "terraform"}],
        "rules": ["terraform"],
    },
    {
        "keys": ("secret", "key vault", "kms"),
        "title": "Secret management",
        "stage": "security",
        "artifacts": [{"name": "secrets.tf", "kind": "terraform"}],
        "rules": ["terraform"],
    },
    {
        "keys": ("monitor", "observability", "prometheus", "grafana", "cloudwatch"),
        "title": "Monitoring and alerting",
        "stage": "infrastructure",
        "artifacts": [{"name": "monitoring.tf", "kind": "terraform"}],
        "rules": ["terraform"],
    },
    {
        "keys": ("github actions", "ci/cd", "pipeline", "workflow"),
        "title": "CI/CD with security scanning",
        "stage": "cicd",
        "artifacts": [{"name": ".github/workflows/ci.yml", "kind": "cicd"}],
        "rules": ["yaml"],
    },
    {
        "keys": ("test", "pytest", "integration"),
        "title": "Integration tests",
        "stage": "testing",
        "artifacts": [{"name": "tests/test_smoke.py", "kind": "python"}],
        "rules": ["python"],
    },
    {
        "keys": ("deploy", "production", "release"),
        "title": "Production deployment",
        "stage": "deployment",
        "artifacts": [{"name": "deployment.yaml", "kind": "yaml"}],
        "rules": ["yaml"],
    },
    {
        "keys": ("tls", "https", "encryption"),
        "title": "Encryption and TLS",
        "stage": "security",
        "artifacts": [{"name": "security.md", "kind": "document"}],
        "rules": [],
    },
]

ALWAYS_TAIL = [
    {
        "title": "Validate artifacts and plans",
        "stage": "validation",
        "artifacts": [{"name": "validation-report.md", "kind": "document"}],
        "rules": [],
    },
    {
        "title": "Architecture and runbook documentation",
        "stage": "documentation",
        "artifacts": [{"name": "architecture.md", "kind": "document"}],
        "rules": [],
    },
]


def _blob(*parts: Any) -> str:
    return " ".join(str(part or "") for part in parts).lower()


def _save_requirement(
    *,
    project_id: str,
    category: str,
    title: str,
    statement: str,
    source: str,
    architecture_run_id: str = "",
    delivery_run_id: str = "",
) -> str:
    req_id = str(uuid.uuid4())
    with SessionLocal() as session:
        session.add(
            ProjectRequirement(
                id=req_id,
                project_id=project_id,
                architecture_run_id=architecture_run_id or "",
                delivery_run_id=delivery_run_id or "",
                category=category[:64],
                title=title[:400],
                statement=statement[:8000],
                source=source[:32],
                status="confirmed",
            )
        )
        session.commit()
    return req_id


def apply_architect_result(
    state: dict[str, Any],
    *,
    run_id: str,
    gated: list[dict[str, Any]],
    delivery_run_id: str = "",
) -> dict[str, Any]:
    """Persist structured requirements, generate the checklist, record risks."""
    project_id = str(state.get("project_id") or "")
    if not project_id:
        return {"ok": False, "reason": "no project"}
    text = _blob(
        state.get("objective"),
        state.get("hld"),
        state.get("reply"),
        state.get("constraints"),
        state.get("mermaid"),
        gated,
    )
    delivery_run_id = delivery_run_id or _latest_delivery_run(project_id)

    _save_requirement(
        project_id=project_id,
        category="functional",
        title="Objective",
        statement=str(state.get("objective") or "")[:8000],
        source="architect",
        architecture_run_id=run_id,
        delivery_run_id=delivery_run_id,
    )
    for assumption in state.get("assumptions") or []:
        _save_requirement(
            project_id=project_id,
            category="assumption",
            title="Assumption",
            statement=str(assumption)[:8000],
            source="architect",
            architecture_run_id=run_id,
            delivery_run_id=delivery_run_id,
        )
        knowledge.remember(
            project_id=project_id,
            summary=f"Assumption: {assumption}",
            kind="requirement",
            category="requirement",
            confidence="low",
            status="draft",
            source="architect",
            extra={"architecture_run_id": run_id},
        )
    for qa in state.get("clarifying_qa") or []:
        _save_requirement(
            project_id=project_id,
            category="clarification",
            title=str(qa.get("q") or "Clarification")[:400],
            statement=str(qa.get("a") or "")[:8000],
            source="user",
            architecture_run_id=run_id,
            delivery_run_id=delivery_run_id,
        )

    existing = {item["title"] for item in task_store.list_tasks(project_id, delivery_run_id)}
    created: list[dict[str, Any]] = []
    previous_id = ""
    for spec in _select_specs(text, gated):
        if spec["title"] in existing:
            continue
        depends = [previous_id] if previous_id else []
        item = task_store.create_task(
            project_id=project_id,
            delivery_run_id=delivery_run_id,
            title=spec["title"],
            description=spec.get("description") or f"Generated from architecture run {run_id}",
            stage=spec["stage"],
            depends_on=depends,
            required_artifacts=spec.get("artifacts") or [],
            validation_rules=spec.get("rules") or [],
            acceptance_criteria=[
                "Required artifacts attached or generated",
                "Validation passed where rules exist",
                "Reviewer approved",
            ],
            architecture_decision_id=str(spec.get("decision_id") or ""),
            ai_recommendation=spec.get("why") or "",
            status="blocked" if depends else "ready",
        )
        created.append(item)
        previous_id = item["id"]
        existing.add(spec["title"])

    risks = _risks_from_text(project_id, text, created)
    activity.record(
        project_id,
        "checklist_generated",
        detail=f"{len(created)} delivery tasks from architecture",
        ref_type="architecture_run",
        ref_id=run_id,
    )
    return {"ok": True, "tasks": len(created), "risks": len(risks), "delivery_run_id": delivery_run_id}


def _select_specs(text: str, gated: list[dict[str, Any]]) -> list[dict[str, Any]]:
    selected: list[dict[str, Any]] = []
    seen: set[str] = set()
    for spec in CATALOG:
        if any(key in text for key in spec["keys"]):
            if spec["title"] not in seen:
                selected.append(dict(spec))
                seen.add(spec["title"])
    if not selected:
        selected.append(
            {
                "title": "Capture architecture baseline",
                "stage": "architecture",
                "artifacts": [{"name": "architecture.md", "kind": "document"}],
                "rules": [],
            }
        )
        selected.append(dict(CATALOG[1]))  # terraform backend
    for decision in gated or []:
        title = str(decision.get("title") or decision.get("decision") or "").strip()
        if title and title not in seen:
            selected.append(
                {
                    "title": f"Implement: {title[:80]}",
                    "stage": "architecture",
                    "artifacts": [{"name": "adr-notes.md", "kind": "document"}],
                    "rules": [],
                    "decision_id": decision.get("id") or "",
                    "why": decision.get("decision") or "",
                }
            )
            seen.add(title)
    for tail in ALWAYS_TAIL:
        if tail["title"] not in seen:
            selected.append(dict(tail))
            seen.add(tail["title"])
    return selected


def _risks_from_text(project_id: str, text: str, created: list[dict[str, Any]]) -> list[str]:
    from app.core.db import ProjectRisk

    findings: list[tuple[str, str, str, str]] = []
    if "multi-region" not in text and "disaster" not in text and "dr " not in text:
        findings.append(
            ("Single-region deployment", "high", "Regional outage with no DR path", "Add a DR / multi-region delivery task")
        )
    if "backup" not in text:
        findings.append(("No backup strategy detected", "high", "Data loss on store failure", "Add database backups"))
    if "monitor" not in text and "observab" not in text:
        findings.append(("Monitoring not specified", "medium", "Incidents detected late", "Add monitoring"))
    if "waf" not in text and "private" not in text:
        findings.append(("Public exposure risk", "medium", "Services may be internet-reachable", "Add private networking / WAF"))
    ids = []
    with SessionLocal() as session:
        for title, severity, impact, rec in findings:
            row = ProjectRisk(
                id=str(uuid.uuid4()),
                project_id=project_id,
                title=title,
                severity=severity,
                impact=impact,
                recommendation=rec,
                href="delivery",
                related_task_id=(created[0]["id"] if created else ""),
            )
            session.add(row)
            ids.append(row.id)
        session.commit()
    return ids


def _latest_delivery_run(project_id: str) -> str:
    with SessionLocal() as session:
        row = session.scalar(
            select(DeliveryRun)
            .where(DeliveryRun.project_id == project_id)
            .order_by(DeliveryRun.created_at.desc())
        )
        return row.id if row else ""


def list_requirements(project_id: str) -> list[dict[str, Any]]:
    with SessionLocal() as session:
        rows = session.scalars(
            select(ProjectRequirement)
            .where(ProjectRequirement.project_id == project_id)
            .order_by(ProjectRequirement.created_at.desc())
        ).all()
        return [
            {
                "id": row.id,
                "category": row.category,
                "title": row.title,
                "statement": row.statement,
                "source": row.source,
                "status": row.status,
                "created_at": row.created_at.isoformat() if row.created_at else None,
            }
            for row in rows
        ]
