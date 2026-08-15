"""Read-only adapters over existing InfraLens functions. Errors return as text."""
from __future__ import annotations

import json
from typing import Any, Optional

CODE_KINDS = [
    "terraform",
    "bicep",
    "dockerfile",
    "kubernetes",
    "workflows",
    "azure_pipelines",
    "ansible",
    "source",
]

RUN_SKILL_ALLOWLIST = frozenset(
    {
        "iac_reviewer",
        "drift_auditor",
        "cost_analyzer",
        "compliance_mapper",
        "code_reviewer",
    }
)


def _clip(value: Any, limit: int = 12000) -> str:
    text = value if isinstance(value, str) else json.dumps(value, default=str)
    return text[:limit]


def _safe(label: str, fn: Any, *args: Any, **kwargs: Any) -> str:
    try:
        result = fn(*args, **kwargs)
        if result is None:
            return f"{label}: (empty)"
        if isinstance(result, dict) and result.get("text"):
            return _clip(result["text"])
        return _clip(result)
    except Exception as exc:  # noqa: BLE001 — tool failures must not kill the graph
        return f"{label} unavailable: {exc}"


def get_cloud_inventory(project_id: str) -> str:
    from app.providers import aws_infra, azure_infra, github_infra

    blocks: list[str] = []
    for name, module in (
        ("azure", azure_infra),
        ("aws", aws_infra),
        ("github", github_infra),
    ):
        try:
            if not module.is_connected(project_id):
                blocks.append(f"{name}: not connected")
                continue
            blocks.append(_safe(name, module.build_environment_report, project_id))
        except Exception as exc:  # noqa: BLE001
            blocks.append(f"{name} unavailable: {exc}")
    return "\n\n".join(blocks) or "No providers connected."


def inventory_is_empty(report: str) -> bool:
    lowered = (report or "").lower()
    if "not connected" in lowered and "resource" not in lowered:
        return True
    useful = [line for line in lowered.splitlines() if line.strip() and "not connected" not in line and "unavailable" not in line and "(empty)" not in line]
    return len(useful) < 2


def get_cost_report(project_id: str, text: str = "") -> str:
    from datetime import date

    from app.providers import azure_infra

    if not azure_infra.is_connected(project_id):
        return "Azure cost: not connected (treat as estimate)."
    try:
        start, end, label = azure_infra.parse_cost_period(text or "last 30 days", today=date.today())
        return _safe("azure cost", azure_infra.build_cost_report, project_id, start, end, label)
    except Exception as exc:  # noqa: BLE001
        return f"Azure cost unavailable: {exc}"


def get_code_artifacts(project_id: str, kinds: Optional[list[str]] = None) -> str:
    from app.providers import github_infra

    if not github_infra.is_connected(project_id):
        return "GitHub code: not connected."
    selected = kinds or list(CODE_KINDS)
    return _safe("github code", github_infra.build_code_report, project_id, selected)


def search_precedent(project_id: str, skill: str = "solution_architect") -> str:
    try:
        from app.platform.engineering.knowledge import architect_context

        ctx = architect_context(project_id)
        if ctx.get("prompt"):
            return _clip(ctx["prompt"], 8000)
    except Exception:
        pass
    from app.platform.memory import list_precedent

    try:
        rows = list_precedent(project_id, skill=skill, limit=8)
        if not rows:
            rows = list_precedent(project_id, limit=8)
        if not rows:
            return "No engineering precedent for this project."
        return _clip(rows, 8000)
    except Exception as exc:  # noqa: BLE001
        return f"Precedent unavailable: {exc}"


def run_skill(name: str, args: dict[str, Any]) -> str:
    from app.skills import registry

    if name not in RUN_SKILL_ALLOWLIST:
        return f"Skill {name} is not on the architect allow-list."
    skill = registry.get(name)
    if skill is None:
        return f"Unknown skill: {name}"
    try:
        return _clip(skill.run(args).content)
    except Exception as exc:  # noqa: BLE001
        return f"{name} failed: {exc}"


def design_resource_plan(args: dict[str, Any]) -> str:
    from app.skills import registry

    skill = registry.get("infrastructure_architect")
    if skill is None:
        return "infrastructure_architect is not registered."
    try:
        return _clip(skill.run(args).content, 16000)
    except Exception as exc:  # noqa: BLE001
        return f"LLD generator failed: {exc}"


def preview_gate(risk_class: str, blast_radius: str, environment: str = "prod") -> dict[str, Any]:
    from app.intelligence import risk_engine

    try:
        decision = risk_engine.classify(
            risk_class or "config_code_change",  # type: ignore[arg-type]
            blast_radius or "medium",  # type: ignore[arg-type]
            environment or "prod",  # type: ignore[arg-type]
        )
        return {
            "gate": decision.gate,
            "label": decision.label,
            "rationale": decision.rationale,
            "requires_approval": decision.requires_approval,
            "two_person": decision.two_person,
        }
    except Exception as exc:  # noqa: BLE001
        return {"gate": "human_approval", "label": "Human approval", "rationale": str(exc)}
