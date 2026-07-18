"""Redis/RQ queue wiring for the workflow engine.

Runs are enqueued by the API ("Run now") and by the scheduler (cron), and are
executed by an ``rq worker intelligence`` process. Only the Redis URL comes from
the environment; everything else is derived here.
"""
import os
from functools import lru_cache

from redis import Redis
from rq import Queue

QUEUE_NAME = "intelligence"
_JOB_PATH = "app.intelligence.worker.run_workflow"


def get_redis_url() -> str:
    return os.environ.get("REDIS_URL", "redis://localhost:6399/0")


@lru_cache(maxsize=1)
def get_redis() -> Redis:
    return Redis.from_url(get_redis_url())


@lru_cache(maxsize=1)
def get_queue() -> Queue:
    return Queue(QUEUE_NAME, connection=get_redis())


def enqueue_run(run_id: str) -> None:
    """Enqueue a workflow run for the worker to pick up."""
    get_queue().enqueue(_JOB_PATH, run_id, job_timeout=900)
