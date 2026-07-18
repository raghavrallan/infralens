"""The RQ job that executes one workflow run.

Runs each of a workflow's read-only skills the same way the chat orchestrator
does — gathering live, read-only context for the connected project, then running
each skill as an agent — and normalizes every skill's output into gated findings
persisted for the dashboard. This module is imported by ``rq worker``.
"""
import re

from rq import SimpleWorker
from rq.timeouts import TimerDeathPenalty

from app import orchestrator
from app.db import init_db
from app.intelligence import findings as findings_mod
from app.intelligence import workflows as store
from app.skills import registry


class Worker(SimpleWorker):
    """Cross-platform RQ worker.

    Runs jobs in-process and enforces timeouts with a timer instead of
    ``SIGALRM`` so it works on Windows (where ``signal.SIGALRM`` is absent) as
    well as Linux. Run it with:
    ``rq worker intelligence --worker-class app.intelligence.worker.Worker``.
    """

    death_penalty_class = TimerDeathPenalty


def _gather_context(objective: str, project_id: str, skills: list[str]) -> str:
    """Fetch the live read-only data the chosen skills need, forced by skill."""
    steps = [orchestrator.PlanStep(skill=name, objective=objective) for name in skills]
    live_context, _charts = orchestrator._gather_live_context(objective, project_id)
    live_context, _charts = orchestrator._ensure_planned_context(
        objective, project_id, steps, live_context, _charts
    )
    return live_context or ""


_CONTEXT_FAILURE_PREFIXES = (
    "LIVE AZURE METRICS FETCH FAILED",
    "LIVE AZURE BILLING FETCH FAILED",
    "LIVE AZURE LOGS FETCH FAILED",
    "LIVE AZURE REQUEST/ERROR TELEMETRY UNAVAILABLE",
    "LIVE AZURE FETCH FAILED",
    "LIVE AWS FETCH FAILED",
    "LIVE GITHUB CODE FETCH FAILED",
    "LIVE GITHUB FETCH FAILED",
)


def _usable_context(context: str) -> str:
    """Drop provider error notices before an unattended skill sees the context.

    Chat should explain provider failures to a user, but a workflow must not
    treat that explanation as evidence and turn it into a finding.
    """
    sections = context.split("\n\n---\n\n")
    usable = [
        section
        for section in sections
        if not section.lstrip().upper().startswith(_CONTEXT_FAILURE_PREFIXES)
    ]
    return "\n\n---\n\n".join(usable).strip()


_CONTEXT_REQUIREMENTS: dict[str, tuple[str, ...]] = {
    "metrics_analyzer": ("LIVE AZURE METRICS DATA",),
    "log_analyzer": (
        "LIVE AZURE REQUEST/ERROR TELEMETRY",
        "LIVE AZURE LOGS & REVISION STATUS",
    ),
    "incident_analyzer": (
        "LIVE AZURE REQUEST/ERROR TELEMETRY",
        "LIVE AZURE LOGS & REVISION STATUS",
        "LIVE AZURE METRICS DATA",
    ),
    "cost_analyzer": ("LIVE AZURE BILLING DATA",),
    "cloud_posture": (
        "LIVE AZURE ENVIRONMENT DATA",
        "LIVE AWS ENVIRONMENT DATA",
        "LIVE GITHUB ENVIRONMENT DATA",
    ),
    "drift_auditor": ("LIVE GITHUB CODE", "LIVE AZURE ENVIRONMENT DATA"),
    "iac_reviewer": ("LIVE GITHUB CODE",),
    "pipeline_auditor": ("LIVE GITHUB CODE",),
    "code_reviewer": ("LIVE GITHUB CODE",),
}


def _has_scanner_or_control_input(objective: str, skill_name: str) -> bool:
    """Return whether a workflow objective contains actual skill input.

    The starter Security & Patch workflow describes scanner work but has no
    scanner payload. Running those skills anyway causes the LLM's request for
    input to be persisted as a high-severity finding.
    """
    text = objective or ""
    lowered = text.lower()
    if skill_name == "vuln_triage":
        return bool(
            re.search(r"\bcve[- ]?\d{4}-\d{4,}\b", text, re.IGNORECASE)
            or (
                any(term in lowered for term in ("trivy", "snyk", "checkmarx", "prisma", "dependabot"))
                and any(term in lowered for term in ("version", "package", "dependency", "severity"))
            )
        )
    if skill_name == "compliance_mapper":
        return len(text) >= 300 and any(
            term in lowered for term in ("evidence", "control", "policy", "audit", "framework")
        )
    return True


def _should_run_skill(skill_name: str, objective: str, context: str) -> bool:
    if skill_name in {"vuln_triage", "compliance_mapper"}:
        return _has_scanner_or_control_input(objective, skill_name)
    required = _CONTEXT_REQUIREMENTS.get(skill_name)
    return not required or any(marker in context for marker in required)


def run_workflow(run_id: str) -> dict[str, int]:
    """Execute a queued workflow run and persist its findings.

    Returns a small summary so the job result is inspectable in RQ.
    """
    init_db()
    run = store.get_run(run_id)
    if run is None:
        return {"findings": 0}

    workflow = store.get_workflow(run["workflow_id"])
    if workflow is None:
        store.mark_run_failed(run_id, "Workflow no longer exists.")
        return {"findings": 0}

    store.mark_run_running(run_id)
    project_id = workflow["project_id"]
    objective = workflow["objective"] or workflow["name"]
    environment = workflow["environment"]
    policy = orchestrator.build_policy("read_only", "ask_approval")

    try:
        live_context = _usable_context(
            _gather_context(objective, project_id, workflow["skills"])
        )
        collected: list[dict] = []
        for skill_name in workflow["skills"]:
            skill = registry.get(skill_name)
            if skill is None or not _should_run_skill(skill_name, objective, live_context):
                continue
            args: dict = {
                "task": objective,
                "objective": objective,
                "operating_policy": policy,
            }
            if live_context:
                args["live_environment"] = live_context
            result = skill.run(args)
            collected.extend(
                findings_mod.build_findings(
                    skill_name,
                    workflow["module"],
                    result.content,
                    objective,
                    environment,
                )
            )
    except Exception as exc:  # noqa: BLE001 - record the failure on the run
        store.mark_run_failed(run_id, str(exc))
        return {"findings": 0}

    count = store.save_findings(run_id, workflow["id"], project_id, collected)
    store.mark_run_succeeded(run_id, count)
    return {"findings": count}
