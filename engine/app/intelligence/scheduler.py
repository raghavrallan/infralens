"""Cron scheduling for workflows, enqueued onto the RQ queue.

A single background scheduler lives in the API process. Enabled workflows that
carry a cron expression get a job that, when it fires, creates a run and hands
it to the queue for the worker to execute. Schedules are re-synced whenever a
workflow is created, edited or deleted.
"""
import logging

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from sqlalchemy import select

from app.intelligence import workflows as store
from app.intelligence.queue import enqueue_run

logger = logging.getLogger(__name__)

_scheduler: BackgroundScheduler | None = None
_REAP_JOB_ID = "reap-stale-runs"


def _reap_stale_work() -> None:
    try:
        store.reap_stale_runs()
    except Exception:
        logger.exception("Could not reap stale workflow runs")
    try:
        from app.agents.solution_architect import governance

        governance.reap_stale_architecture_runs()
    except Exception:
        logger.exception("Could not reap stale architecture runs")
    try:
        from app.platform import delivery

        delivery.reap_stale_architecture_jobs()
    except Exception:
        logger.exception("Could not reap stale delivery architecture jobs")


def _ensure_reap_job() -> None:
    if _scheduler is None:
        return
    _scheduler.add_job(
        _reap_stale_work,
        "interval",
        minutes=5,
        id=_REAP_JOB_ID,
        replace_existing=True,
    )


def _enqueue_scheduled(workflow_id: str) -> None:
    run = store.create_run(workflow_id, trigger="scheduled")
    if run is None:
        return
    try:
        enqueue_run(run["id"])
    except Exception as exc:  # noqa: BLE001 - queue may be down; record and move on
        store.mark_run_failed(run["id"], f"Could not enqueue run: {exc}")
        logger.warning("Failed to enqueue scheduled run for %s: %s", workflow_id, exc)


def _pause_workflows_without_cloud() -> None:
    """Disable scheduled workflows when the project has no Azure/AWS connection."""
    from app.platform import connections
    from app.core.db import Project, SessionLocal, Workflow

    with SessionLocal() as session:
        for project in session.scalars(select(Project)).all():
            azure_ok = connections.status(project.id, "azure").get("connected")
            aws_ok = connections.status(project.id, "aws").get("connected")
            if azure_ok or aws_ok:
                continue
            for wf in session.scalars(
                select(Workflow).where(
                    Workflow.project_id == project.id,
                    Workflow.enabled.is_(True),
                )
            ).all():
                wf.enabled = False
        session.commit()


def sync_schedules() -> None:
    """Rebuild the cron jobs from the current set of scheduled workflows."""
    if _scheduler is None:
        return
    _scheduler.remove_all_jobs()
    try:
        _pause_workflows_without_cloud()
    except Exception:
        logger.exception("Could not pause workflows for projects without cloud accounts")
    for workflow in store.scheduled_workflows():
        cron = workflow.get("schedule_cron", "")
        try:
            trigger = CronTrigger.from_crontab(cron)
        except (ValueError, TypeError):
            logger.warning(
                "Skipping workflow %s: invalid cron %r", workflow["id"], cron
            )
            continue
        _scheduler.add_job(
            _enqueue_scheduled,
            trigger=trigger,
            id=workflow["id"],
            args=[workflow["id"]],
            replace_existing=True,
        )
    _ensure_reap_job()


def start_scheduler() -> None:
    global _scheduler
    if _scheduler is not None:
        return
    _scheduler = BackgroundScheduler(timezone="UTC")
    _scheduler.start()
    sync_schedules()


def shutdown_scheduler() -> None:
    global _scheduler
    if _scheduler is not None:
        _scheduler.shutdown(wait=False)
        _scheduler = None
