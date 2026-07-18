"""Cron scheduling for workflows, enqueued onto the RQ queue.

A single background scheduler lives in the API process. Enabled workflows that
carry a cron expression get a job that, when it fires, creates a run and hands
it to the queue for the worker to execute. Schedules are re-synced whenever a
workflow is created, edited or deleted.
"""
import logging

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from app.intelligence import workflows as store
from app.intelligence.queue import enqueue_run

logger = logging.getLogger(__name__)

_scheduler: BackgroundScheduler | None = None


def _enqueue_scheduled(workflow_id: str) -> None:
    run = store.create_run(workflow_id, trigger="scheduled")
    if run is None:
        return
    try:
        enqueue_run(run["id"])
    except Exception as exc:  # noqa: BLE001 - queue may be down; record and move on
        store.mark_run_failed(run["id"], f"Could not enqueue run: {exc}")
        logger.warning("Failed to enqueue scheduled run for %s: %s", workflow_id, exc)


def sync_schedules() -> None:
    """Rebuild the cron jobs from the current set of scheduled workflows."""
    if _scheduler is None:
        return
    _scheduler.remove_all_jobs()
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
