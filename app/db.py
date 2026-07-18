"""Database layer: SQLAlchemy engine, session, models and initialisation.

All app configuration (Azure OpenAI settings) and provider connections are
persisted in Postgres rather than environment variables or local files. Only
the Postgres connection string itself comes from the environment.
"""
import os
from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import DateTime, String, create_engine, inspect, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker

DEFAULT_DATABASE_URL = (
    "postgresql+psycopg2://devsecops:devsecops@localhost:5544/devsecops"
)

DEFAULT_PROJECT_ID = "default"


def get_database_url() -> str:
    return os.environ.get("DATABASE_URL", DEFAULT_DATABASE_URL)


engine = create_engine(get_database_url(), pool_pre_ping=True, future=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


class AppConfig(Base):
    """Key/value store for application configuration (e.g. Azure OpenAI)."""

    __tablename__ = "app_config"

    key: Mapped[str] = mapped_column(String(128), primary_key=True)
    value: Mapped[str] = mapped_column(String, default="")


def _now() -> datetime:
    return datetime.now(timezone.utc)


class Project(Base):
    """A workspace that isolates its own connections, chats and mapped repos."""

    __tablename__ = "projects"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    name: Mapped[str] = mapped_column(String(120), default="New project")
    # GitHub repositories ("owner/name") this project is allowed to inspect.
    repos: Mapped[list[str]] = mapped_column(JSONB, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now
    )


class Connection(Base):
    """A stored provider connection (Azure / AWS / GitHub), scoped to a project."""

    __tablename__ = "connections"

    project_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    provider: Mapped[str] = mapped_column(String(32), primary_key=True)
    method: Mapped[str] = mapped_column(String(64))
    fields: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    connected_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )


class Chat(Base):
    """A saved conversation, scoped to a project."""

    __tablename__ = "chats"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    project_id: Mapped[str] = mapped_column(String(36), index=True, default=DEFAULT_PROJECT_ID)
    title: Mapped[str] = mapped_column(String(200), default="New chat")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now
    )


class Message(Base):
    """A single message belonging to a chat."""

    __tablename__ = "messages"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    chat_id: Mapped[str] = mapped_column(String(36), index=True)
    role: Mapped[str] = mapped_column(String(16))
    content: Mapped[str] = mapped_column(String, default="")
    meta: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class Workflow(Base):
    """A saved set of diagnose skills that run together on a schedule/on demand."""

    __tablename__ = "workflows"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    project_id: Mapped[str] = mapped_column(String(36), index=True, default=DEFAULT_PROJECT_ID)
    name: Mapped[str] = mapped_column(String(160), default="New workflow")
    objective: Mapped[str] = mapped_column(String, default="")
    module: Mapped[str] = mapped_column(String(64), default="")
    environment: Mapped[str] = mapped_column(String(16), default="prod")
    skills: Mapped[list[str]] = mapped_column(JSONB, default=list)
    schedule_cron: Mapped[str] = mapped_column(String(64), default="")
    enabled: Mapped[bool] = mapped_column(default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now
    )


class WorkflowRun(Base):
    """One execution of a workflow, tracked from queued to finished."""

    __tablename__ = "workflow_runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    workflow_id: Mapped[str] = mapped_column(String(36), index=True)
    project_id: Mapped[str] = mapped_column(String(36), index=True, default=DEFAULT_PROJECT_ID)
    status: Mapped[str] = mapped_column(String(16), default="queued")
    trigger: Mapped[str] = mapped_column(String(16), default="manual")
    finding_count: Mapped[int] = mapped_column(default=0)
    error: Mapped[str] = mapped_column(String, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    started_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    finished_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class Finding(Base):
    """A single issue a workflow run surfaced, with its gate decision."""

    __tablename__ = "findings"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    run_id: Mapped[str] = mapped_column(String(36), index=True)
    workflow_id: Mapped[str] = mapped_column(String(36), index=True)
    project_id: Mapped[str] = mapped_column(String(36), index=True, default=DEFAULT_PROJECT_ID)
    skill: Mapped[str] = mapped_column(String(64), default="")
    module: Mapped[str] = mapped_column(String(64), default="")
    severity: Mapped[str] = mapped_column(String(16), default="low")
    title: Mapped[str] = mapped_column(String(400), default="")
    resource: Mapped[str] = mapped_column(String(400), default="")
    category: Mapped[str] = mapped_column(String(120), default="")
    evidence: Mapped[str] = mapped_column(String, default="")
    recommended_action: Mapped[str] = mapped_column(String, default="")
    risk_class: Mapped[str] = mapped_column(String(32), default="config_code_change")
    blast_radius: Mapped[str] = mapped_column(String(16), default="medium")
    gate_decision: Mapped[str] = mapped_column(String(32), default="human_approval")
    gate_label: Mapped[str] = mapped_column(String(64), default="")
    gate_rationale: Mapped[str] = mapped_column(String, default="")
    status: Mapped[str] = mapped_column(String(16), default="open")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class Approval(Base):
    """Scaffold for time-boxed approvals — populated by a later milestone."""

    __tablename__ = "approvals"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    finding_id: Mapped[str] = mapped_column(String(36), index=True)
    project_id: Mapped[str] = mapped_column(String(36), index=True, default=DEFAULT_PROJECT_ID)
    gate: Mapped[str] = mapped_column(String(32), default="human_approval")
    decision: Mapped[str] = mapped_column(String(16), default="pending")
    decided_by: Mapped[str] = mapped_column(String(120), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    expires_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class EngineeringMemory(Base):
    """Scaffold for retrievable precedent — approved/rejected actions + outcomes."""

    __tablename__ = "engineering_memory"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    project_id: Mapped[str] = mapped_column(String(36), index=True, default=DEFAULT_PROJECT_ID)
    kind: Mapped[str] = mapped_column(String(32), default="finding")
    ref_id: Mapped[str] = mapped_column(String(36), default="")
    summary: Mapped[str] = mapped_column(String, default="")
    outcome: Mapped[str] = mapped_column(String(32), default="")
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


def _pk_columns(conn: Any, table: str) -> list[str]:
    rows = conn.execute(
        text(
            "SELECT a.attname FROM pg_index i "
            "JOIN pg_attribute a ON a.attrelid = i.indrelid "
            "AND a.attnum = ANY(i.indkey) "
            "WHERE i.indrelid = to_regclass(:t) AND i.indisprimary"
        ),
        {"t": table},
    )
    return [r[0] for r in rows]


def _migrate() -> None:
    """Bring pre-project databases up to the project-scoped schema (idempotent)."""
    inspector = inspect(engine)
    tables = set(inspector.get_table_names())

    with engine.begin() as conn:
        # Ensure a default project exists to hold pre-existing data.
        conn.execute(
            text(
                "INSERT INTO projects (id, name, repos, created_at, updated_at) "
                "VALUES (:id, :name, '[]'::jsonb, now(), now()) "
                "ON CONFLICT (id) DO NOTHING"
            ),
            {"id": DEFAULT_PROJECT_ID, "name": "Default project"},
        )

        if "connections" in tables:
            cols = {c["name"] for c in inspector.get_columns("connections")}
            if "project_id" not in cols:
                conn.execute(
                    text("ALTER TABLE connections ADD COLUMN project_id VARCHAR(36)")
                )
            conn.execute(
                text(
                    "UPDATE connections SET project_id = :pid WHERE project_id IS NULL"
                ),
                {"pid": DEFAULT_PROJECT_ID},
            )
            if _pk_columns(conn, "connections") == ["provider"]:
                conn.execute(
                    text("ALTER TABLE connections DROP CONSTRAINT IF EXISTS connections_pkey")
                )
                conn.execute(
                    text("ALTER TABLE connections ALTER COLUMN project_id SET NOT NULL")
                )
                conn.execute(
                    text(
                        "ALTER TABLE connections ADD PRIMARY KEY (project_id, provider)"
                    )
                )

        if "chats" in tables:
            cols = {c["name"] for c in inspector.get_columns("chats")}
            if "project_id" not in cols:
                conn.execute(text("ALTER TABLE chats ADD COLUMN project_id VARCHAR(36)"))
            conn.execute(
                text("UPDATE chats SET project_id = :pid WHERE project_id IS NULL"),
                {"pid": DEFAULT_PROJECT_ID},
            )


def init_db() -> None:
    """Create tables if they do not exist, then apply lightweight migrations."""
    Base.metadata.create_all(engine)
    _migrate()
