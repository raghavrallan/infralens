#!/usr/bin/env python3
"""Copy a legacy Infralens SQLite file into the Postgres database.

Ids are kept. Rows that already exist are left in place. Run from the repo
root after Postgres is up:

  PYTHONPATH=engine .venv/bin/python scripts/migrate_sqlite_to_postgres.py
"""
from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import text

from app.core.db import SessionLocal, init_db

ROOT = Path(__file__).resolve().parents[1]
SQLITE = ROOT / "data" / "infralens.sqlite"


def _ms(value: int | None) -> datetime:
    stamp = int(value or 0) / 1000
    return datetime.fromtimestamp(stamp, tz=timezone.utc)


def _username(email: str, user_id: str) -> str:
    clean = (email or "").strip().lower()
    if 0 < len(clean) <= 64:
        return clean
    return f"{clean[:48]}-{user_id[:8]}"[:64]


def main() -> None:
    init_db()
    if not SQLITE.exists():
        print("No data/infralens.sqlite file. Nothing to copy.")
        return
    source = sqlite3.connect(SQLITE)
    source.row_factory = sqlite3.Row
    copied = 0
    with SessionLocal() as session:
        for row in source.execute("SELECT * FROM organizations"):
            session.execute(
                text(
                    "INSERT INTO organizations (id, name, slug, created_by, created_at, updated_at) "
                    "VALUES (:id, :name, :slug, '', :created_at, :created_at) "
                    "ON CONFLICT (id) DO NOTHING"
                ),
                {
                    "id": row["id"],
                    "name": row["name"],
                    "slug": row["slug"],
                    "created_at": _ms(row["created_at"]),
                },
            )
            copied += 1
        for row in source.execute("SELECT * FROM users"):
            session.execute(
                text(
                    "INSERT INTO users (id, username, email, display_name, password_hash, role, is_active, created_at, updated_at) "
                    "VALUES (:id, :username, :email, :name, :password_hash, 'org_admin', true, :created_at, :created_at) "
                    "ON CONFLICT (id) DO NOTHING"
                ),
                {
                    "id": row["id"],
                    "username": _username(row["email"], row["id"]),
                    "email": row["email"],
                    "name": row["name"],
                    "password_hash": row["password_hash"],
                    "created_at": _ms(row["created_at"]),
                },
            )
        for row in source.execute("SELECT * FROM memberships"):
            session.execute(
                text(
                    "INSERT INTO org_memberships (id, org_id, user_id, org_role, created_at) "
                    "VALUES (:id, :org_id, :user_id, :role, :created_at) "
                    "ON CONFLICT (id) DO NOTHING"
                ),
                {
                    "id": f"{row['org_id'][:16]}{row['user_id'][:16]}",
                    "org_id": row["org_id"],
                    "user_id": row["user_id"],
                    "role": row["role"],
                    "created_at": _ms(row["created_at"]),
                },
            )
        for row in source.execute("SELECT * FROM projects"):
            session.execute(
                text(
                    "INSERT INTO projects (id, org_id, name, slug, budget_usd, repos, created_at, updated_at) "
                    "VALUES (:id, :org_id, :name, :slug, :budget, '[]'::jsonb, :created_at, :created_at) "
                    "ON CONFLICT (id) DO UPDATE SET slug = EXCLUDED.slug, budget_usd = EXCLUDED.budget_usd, org_id = EXCLUDED.org_id"
                ),
                {
                    "id": row["id"],
                    "org_id": row["org_id"],
                    "name": row["name"],
                    "slug": row["slug"],
                    "budget": row["budget_usd"],
                    "created_at": _ms(row["created_at"]),
                },
            )
        for row in source.execute("SELECT * FROM project_members"):
            session.execute(
                text(
                    "INSERT INTO project_memberships (id, project_id, user_id, project_role, created_at) "
                    "VALUES (:id, :project_id, :user_id, :role, now()) "
                    "ON CONFLICT (id) DO NOTHING"
                ),
                {
                    "id": f"{row['project_id'][:16]}{row['user_id'][:16]}",
                    "project_id": row["project_id"],
                    "user_id": row["user_id"],
                    "role": row["role"],
                },
            )
        for row in source.execute("SELECT * FROM azure_connections"):
            session.execute(
                text(
                    "INSERT INTO azure_connections (id, org_id, name, tenant_id, client_id, secret_cipher, status, status_detail, last_checked_at, created_at) "
                    "VALUES (:id, :org_id, :name, :tenant_id, :client_id, :secret, :status, :detail, :checked, :created_at) "
                    "ON CONFLICT (id) DO NOTHING"
                ),
                {
                    "id": row["id"],
                    "org_id": row["org_id"],
                    "name": row["name"],
                    "tenant_id": row["tenant_id"],
                    "client_id": row["client_id"],
                    "secret": row["secret_cipher"],
                    "status": row["status"],
                    "detail": row["status_detail"] or "",
                    "checked": row["last_checked_at"],
                    "created_at": row["created_at"],
                },
            )
        for row in source.execute("SELECT * FROM subscriptions"):
            session.execute(
                text(
                    "INSERT INTO subscriptions (id, org_id, connection_id, name, state) "
                    "VALUES (:id, :org_id, :connection_id, :name, :state) "
                    "ON CONFLICT (id) DO NOTHING"
                ),
                dict(row),
            )
        for row in source.execute("SELECT * FROM project_subscriptions"):
            session.execute(
                text(
                    "INSERT INTO project_subscriptions (project_id, subscription_id) "
                    "VALUES (:project_id, :subscription_id) ON CONFLICT DO NOTHING"
                ),
                dict(row),
            )
        for row in source.execute("SELECT * FROM project_connections"):
            session.execute(
                text(
                    "INSERT INTO project_connections (project_id, connection_id) "
                    "VALUES (:project_id, :connection_id) ON CONFLICT DO NOTHING"
                ),
                dict(row),
            )
        now_ms = int(datetime.now(tz=timezone.utc).timestamp() * 1000)
        for row in source.execute("SELECT * FROM sessions"):
            if int(row["expires_at"] or 0) < now_ms:
                continue
            session.execute(
                text(
                    "INSERT INTO sessions (token_hash, user_id, org_id, expires_at) "
                    "VALUES (:token_hash, :user_id, :org_id, :expires_at) "
                    "ON CONFLICT (token_hash) DO NOTHING"
                ),
                dict(row),
            )
        session.commit()
    source.close()
    print(f"SQLite rows considered: {copied} organizations. Existing Postgres rows were kept.")


if __name__ == "__main__":
    main()
