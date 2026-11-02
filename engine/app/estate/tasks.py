import os
import subprocess
from pathlib import Path

from sqlalchemy import text

from app.core.db import SessionLocal
from app.estate.celery_app import celery

ROOT = Path(__file__).resolve().parents[3]
INTERVALS = {"3h": 3 * 60 * 60 * 1000, "12h": 12 * 60 * 60 * 1000, "7d": 7 * 24 * 60 * 60 * 1000}


def _claim(org_id: str, project_id: str, range_id: str) -> bool:
    import time

    now = int(time.time() * 1000)
    stale = now - 15 * 60 * 1000
    with SessionLocal() as session:
        row = session.execute(
            text(
                """
                INSERT INTO estate_syncs (org_id, project_id, range_id, started_at)
                VALUES (:org, :project, :range, :now)
                ON CONFLICT (org_id, project_id, range_id)
                DO UPDATE SET started_at = EXCLUDED.started_at
                WHERE estate_syncs.started_at < :stale
                RETURNING org_id
                """
            ),
            {"org": org_id, "project": project_id, "range": range_id, "now": now, "stale": stale},
        ).first()
        session.commit()
        return row is not None


@celery.task(name="app.estate.tasks.sync_estate")
def sync_estate(org_id: str, project_id: str, range_id: str) -> None:
    env = os.environ.copy()
    env["PYTHONPATH"] = str(ROOT / "engine")
    subprocess.run(
        ["node", str(ROOT / "scripts" / "sync-estate.mjs"), org_id, project_id, range_id],
        cwd=ROOT,
        env=env,
        check=False,
    )


@celery.task(name="app.estate.tasks.sweep")
def sweep() -> None:
    import time

    now = int(time.time() * 1000)
    try:
        with SessionLocal() as session:
            locked = session.execute(text("SELECT pg_try_advisory_xact_lock(842170)")).scalar()
            if not locked:
                return
            rows = session.execute(
                text(
                    """
                    SELECT s.org_id, s.project_id, s.range_id, s.synced_at, COALESCE(sch.cadence, '12h') AS cadence
                    FROM estate_snapshots s
                    LEFT JOIN estate_schedules sch ON sch.org_id = s.org_id AND sch.project_id = s.project_id
                    """
                )
            ).all()
            for row in rows:
                interval = INTERVALS.get(row.cadence)
                if interval is None or now - int(row.synced_at) < interval:
                    continue
                if _claim(row.org_id, row.project_id, row.range_id):
                    sync_estate.delay(row.org_id, row.project_id, row.range_id)
            session.commit()
    except Exception:
        return
