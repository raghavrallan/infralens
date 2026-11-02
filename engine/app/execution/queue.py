"""Org-scoped provider queues carrying only action IDs."""
import os
from functools import lru_cache

from rq import Queue
from rq import Worker

from app.intelligence.queue import get_redis

_JOB_PATH = "executors.common.rq_job.execute_provider_job"


def queue_name(org_id: str, provider: str, access_scope: str) -> str:
    """Return the org-isolated RQ queue name for a provider scope."""
    clean_org = (org_id or "").strip()
    if not clean_org:
        raise ValueError("org_id is required for provider queues")
    scope = "write" if access_scope == "write" else "read"
    return f"org.{clean_org}.provider.{provider}.{scope}"


def provider_queue_names(org_id: str, provider: str) -> list[str]:
    """Both read and write queues for one org provider pair."""
    return [
        queue_name(org_id, provider, "read_only"),
        queue_name(org_id, provider, "write"),
    ]


@lru_cache(maxsize=64)
def get_queue(name: str) -> Queue:
    return Queue(name, connection=get_redis())


def queue_depth(org_id: str, provider: str | None = None) -> int:
    """Total waiting jobs across org provider queues (optionally one provider)."""
    providers = [provider] if provider else ["azure", "aws", "github"]
    total = 0
    for item in providers:
        for scope in ("read_only", "write"):
            try:
                total += get_queue(queue_name(org_id, item, scope)).count
            except Exception:  # noqa: BLE001
                continue
    return total


def queue_snapshot(
    org_id: str, provider: str, access_scope: str, action_id: str = ""
) -> dict[str, object]:
    """Return safe RQ/worker diagnostics; never include job arguments or credentials."""
    name = queue_name(org_id, provider, access_scope)
    try:
        connection = get_redis()
        queue = get_queue(name)
        workers: list[dict[str, object]] = []
        rq_job_id = ""
        if action_id:
            for job in queue.get_jobs(0, 200):
                if job.args and str(job.args[0]) == action_id:
                    rq_job_id = job.id
                    break
        for worker in Worker.all(connection=connection):
            queues = [item.name for item in worker.queues]
            if name in queues:
                workers.append(
                    {"name": worker.name, "state": worker.get_state(), "queues": queues}
                )
        return {
            "queue": name,
            "org_id": org_id,
            "queue_depth": queue.count,
            "workers": workers,
            "executor_available": bool(workers),
            "redis_available": True,
            "rq_job_id": rq_job_id,
        }
    except Exception as exc:  # noqa: BLE001 - diagnostics must not break action control
        return {
            "queue": name,
            "org_id": org_id,
            "queue_depth": None,
            "workers": [],
            "executor_available": False,
            "redis_available": False,
            "diagnostic_error": str(exc)[:300],
            "rq_job_id": "",
        }


def enqueue_action(
    action_id: str, org_id: str, provider: str, access_scope: str
) -> dict[str, object]:
    """Enqueue only the opaque action ID, never credentials or operation payload."""
    job = get_queue(queue_name(org_id, provider, access_scope)).enqueue(
        _JOB_PATH,
        action_id,
        provider,
        job_timeout=int(os.environ.get("EXECUTOR_JOB_TIMEOUT", "900")),
    )
    return {
        "rq_job_id": job.id,
        **queue_snapshot(org_id, provider, access_scope, action_id),
    }
