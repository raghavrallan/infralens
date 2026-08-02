"""Start an RQ worker for org-scoped provider queues.

Reads EXECUTOR_ORG_ID and EXECUTOR_PROVIDER from the environment so the same
image can serve any organization pool.
"""
from __future__ import annotations

import os
import sys


def main(argv: list[str] | None = None) -> int:
    del argv  # entrypoint ignores passthrough args; env drives queue selection
    org_id = (os.environ.get("EXECUTOR_ORG_ID") or "").strip()
    provider = (os.environ.get("EXECUTOR_PROVIDER") or "").strip().lower()
    redis_url = os.environ.get("REDIS_URL", "redis://redis:6379/0")
    if not org_id:
        print("EXECUTOR_ORG_ID is required", file=sys.stderr)
        return 64
    if provider not in {"azure", "aws", "github"}:
        print("EXECUTOR_PROVIDER must be azure, aws, or github", file=sys.stderr)
        return 64
    read_q = f"org.{org_id}.provider.{provider}.read"
    write_q = f"org.{org_id}.provider.{provider}.write"
    print(f"[executor] org={org_id} provider={provider} queues={read_q},{write_q}")
    from rq.cli import main as rq_main

    sys.argv = [
        "rq",
        "worker",
        read_q,
        write_q,
        "--worker-class",
        "executors.common.worker.Worker",
        "--url",
        redis_url,
    ]
    rq_main()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
