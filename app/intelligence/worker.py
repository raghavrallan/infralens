"""The RQ job that executes one workflow run.

Runs each of a workflow's read-only skills the same way the chat orchestrator
does — gathering live, read-only context for the connected project, then running
each skill as an agent — and normalizes every skill's output into gated findings
persisted for the dashboard. This module is imported by ``rq worker``.
"""
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
        live_context = _gather_context(objective, project_id, workflow["skills"])
        collected: list[dict] = []
        for skill_name in workflow["skills"]:
            skill = registry.get(skill_name)
            if skill is None:
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
