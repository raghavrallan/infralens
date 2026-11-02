import os
from pathlib import Path

from celery import Celery
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[3] / ".env")


def broker_url() -> str:
    url = os.environ.get("REDIS_URL", "redis://localhost:6399/0")
    if url.endswith("/0"):
        return f"{url[:-1]}1"
    return f"{url.rstrip('/')}/1"


celery = Celery("infralens.estate", broker=broker_url(), backend=broker_url())
celery.conf.update(
    imports=("app.estate.tasks",),
    task_default_queue="estate",
    task_ignore_result=True,
    broker_connection_retry_on_startup=True,
    beat_schedule={
        "estate-sweep": {"task": "app.estate.tasks.sweep", "schedule": 600.0},
    },
    timezone="UTC",
)
