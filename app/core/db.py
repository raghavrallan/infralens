"""Database layer: SQLAlchemy engine, session, models and initialisation.

All app configuration (Azure OpenAI settings) and provider connections are
persisted in Postgres rather than environment variables or local files. Only
the Postgres connection string itself comes from the environment.
"""
import os
from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import Boolean, DateTime, Integer, String, create_engine, inspect, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker

DEFAULT_DATABASE_URL = (
    "postgresql+psycopg2://devsecops:devsecops@localhost:5544/devsecops"
)

DEFAULT_PROJECT_ID = "default"
DEFAULT_PROJECT_CONFIG_KEY = "default_project_id"
# Stable ID for the seeded default org so local executors can set EXECUTOR_ORG_ID.
DEFAULT_ORG_ID = "00000000-0000-4000-8000-000000000001"
DEFAULT_ORG_SLUG = "infralens"
# JSON list of project ids hidden when the DB role cannot DELETE root_admin tables.
DELETED_PROJECTS_CONFIG_KEY = "deleted_project_ids"


def get_database_url() -> str:
    return os.environ.get("DATABASE_URL", DEFAULT_DATABASE_URL)


# Azure Database for PostgreSQL is remote from the Container App.  A pre-ping
# on every session checkout adds another network round-trip to every API read.
# Recycle pooled connections instead, with an opt-in override for environments
# where aggressive stale-connection detection is more important than latency.
_pool_pre_ping = os.environ.get("DB_POOL_PRE_PING", "false").lower() == "true"
engine = create_engine(
    get_database_url(),
    future=True,
    pool_pre_ping=_pool_pre_ping,
    pool_recycle=1800,
    pool_timeout=30,
    pool_size=5,
    max_overflow=5,
)
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


class User(Base):
    """UI login account. Seeded on startup; passwords are stored hashed."""

    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    username: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    email: Mapped[str] = mapped_column(String(255), default="", index=True)
    display_name: Mapped[str] = mapped_column(String(120), default="Admin")
    password_hash: Mapped[str] = mapped_column(String(255))
    # Global role: super_admin | org_admin | devops_lead | devops_engineer | developer | viewer
    # Effective project powers also come from project_memberships.project_role.
    role: Mapped[str] = mapped_column(String(32), default="developer")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now
    )


class Organization(Base):
    """Tenant boundary: projects and users are isolated per organization."""

    __tablename__ = "organizations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    name: Mapped[str] = mapped_column(String(120), default="Organization")
    slug: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    created_by: Mapped[str] = mapped_column(String(36), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now
    )


class OrgExecutorSettings(Base):
    """Per-org CLI executor pool schedule and scale state."""

    __tablename__ = "org_executor_settings"

    org_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    # on_demand | window | schedule
    mode: Mapped[str] = mapped_column(String(32), default="on_demand")
    window_hours: Mapped[int] = mapped_column(Integer, default=12)
    window_ends_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    schedule: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    idle_scale_down_minutes: Mapped[int] = mapped_column(Integer, default=15)
    max_replicas: Mapped[int] = mapped_column(Integer, default=1)
    desired_state: Mapped[str] = mapped_column(String(32), default="scaled_to_zero")
    actual_state: Mapped[str] = mapped_column(String(32), default="scaled_to_zero")
    last_job_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_error: Mapped[str] = mapped_column(String, default="")
    aca_app_names: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now
    )


class OrgMembership(Base):
    """User membership in an organization (org_admin or member)."""

    __tablename__ = "org_memberships"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    org_id: Mapped[str] = mapped_column(String(36), index=True)
    user_id: Mapped[str] = mapped_column(String(36), index=True)
    # org_admin | member
    org_role: Mapped[str] = mapped_column(String(32), default="member")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class ProjectMembership(Base):
    """User membership in a project with a project-scoped role."""

    __tablename__ = "project_memberships"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    project_id: Mapped[str] = mapped_column(String(36), index=True)
    user_id: Mapped[str] = mapped_column(String(36), index=True)
    # devops_lead | devops_engineer | developer | viewer
    project_role: Mapped[str] = mapped_column(String(32), default="developer")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class Invite(Base):
    """Email invite into an organization (and optionally a project)."""

    __tablename__ = "invites"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    org_id: Mapped[str] = mapped_column(String(36), index=True)
    email: Mapped[str] = mapped_column(String(255), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    invited_role: Mapped[str] = mapped_column(String(32), default="developer")
    org_role: Mapped[str] = mapped_column(String(32), default="member")
    project_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True)
    project_role: Mapped[str] = mapped_column(String(32), default="developer")
    status: Mapped[str] = mapped_column(String(16), default="pending")
    invited_by: Mapped[str] = mapped_column(String(36), default="")
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    accepted_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class MembershipRequest(Base):
    """DevOps Lead proposal to add/remove/update a project member; Org Admin approves."""

    __tablename__ = "membership_requests"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    org_id: Mapped[str] = mapped_column(String(36), index=True)
    project_id: Mapped[str] = mapped_column(String(36), index=True)
    # add | remove | update_role
    action: Mapped[str] = mapped_column(String(16), default="add")
    target_email: Mapped[str] = mapped_column(String(255), default="")
    target_user_id: Mapped[str] = mapped_column(String(36), default="")
    project_role: Mapped[str] = mapped_column(String(32), default="developer")
    status: Mapped[str] = mapped_column(String(16), default="pending")
    reason: Mapped[str] = mapped_column(String, default="")
    requested_by: Mapped[str] = mapped_column(String(36), default="")
    decided_by: Mapped[str] = mapped_column(String(36), default="")
    approve_token_hash: Mapped[str] = mapped_column(String(64), default="", index=True)
    expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    decided_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class BreakGlassSession(Base):
    """Time-boxed gate downgrade window opened by DevOps Lead+."""

    __tablename__ = "break_glass_sessions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    project_id: Mapped[str] = mapped_column(String(36), index=True, default=DEFAULT_PROJECT_ID)
    opened_by: Mapped[str] = mapped_column(String(120), default="")
    reason: Mapped[str] = mapped_column(String, default="")
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    postmortem_required: Mapped[bool] = mapped_column(Boolean, default=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    closed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class DeliveryRun(Base):
    """Staged docs → architecture → TF → apply → code delivery for a project."""

    __tablename__ = "delivery_runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    project_id: Mapped[str] = mapped_column(String(36), index=True)
    stage: Mapped[str] = mapped_column(String(32), default="ingest")
    status: Mapped[str] = mapped_column(String(32), default="active")
    artifacts: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    approved_by: Mapped[str] = mapped_column(String(120), default="")
    created_by: Mapped[str] = mapped_column(String(120), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now
    )


class Project(Base):
    """A workspace that isolates its own connections, chats and mapped repos."""

    __tablename__ = "projects"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    org_id: Mapped[str] = mapped_column(String(36), index=True, default="")
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


class ChatMemory(Base):
    """Compact, project-scoped memory used for same-chat follow-ups."""

    __tablename__ = "chat_memories"

    chat_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    project_id: Mapped[str] = mapped_column(String(36), index=True)
    summary: Mapped[str] = mapped_column(String, default="")
    facts: Mapped[list[Any]] = mapped_column(JSONB, default=list)
    references: Mapped[list[Any]] = mapped_column(JSONB, default=list)
    unresolved: Mapped[list[Any]] = mapped_column(JSONB, default=list)
    # Structured requirement / infra / deployment tracking for smart chat.
    requirements: Mapped[list[Any]] = mapped_column(JSONB, default=list)
    infra_state: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    deployment_outcomes: Mapped[list[Any]] = mapped_column(JSONB, default=list)
    source_message_count: Mapped[int] = mapped_column(default=0)
    version: Mapped[int] = mapped_column(default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now
    )


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


class FindingIdentity(Base):
    """Stable issue key so repeated workflow runs update one finding instead of cloning it.

    Owned by the app role (create_all) because Azure ``findings`` is root_admin-owned
    and cannot be ALTERed by the application user.
    """

    __tablename__ = "finding_identities"

    fingerprint: Mapped[str] = mapped_column(String(64), primary_key=True)
    project_id: Mapped[str] = mapped_column(String(36), index=True)
    finding_id: Mapped[str] = mapped_column(String(36), index=True)
    occurrence_count: Mapped[int] = mapped_column(Integer, default=1)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


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


class ArchitectureRun(Base):
    """Catalog row for a Solution Architect graph run (chat or delivery)."""

    __tablename__ = "architecture_runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    thread_id: Mapped[str] = mapped_column(String(64), index=True, default="")
    project_id: Mapped[str] = mapped_column(String(36), index=True, default=DEFAULT_PROJECT_ID)
    user_id: Mapped[str] = mapped_column(String(120), default="")
    objective: Mapped[str] = mapped_column(String, default="")
    tier: Mapped[str] = mapped_column(String(8), default="T1")
    mode: Mapped[str] = mapped_column(String(16), default="greenfield")
    source: Mapped[str] = mapped_column(String(16), default="chat")
    status: Mapped[str] = mapped_column(String(24), default="running")
    pending_question: Mapped[str] = mapped_column(String, default="")
    checkpoint: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now
    )


class ArchitectureDecision(Base):
    """One ADR produced by a Solution Architect run."""

    __tablename__ = "architecture_decisions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    run_id: Mapped[str] = mapped_column(String(36), index=True)
    title: Mapped[str] = mapped_column(String(400), default="")
    context: Mapped[str] = mapped_column(String, default="")
    options_considered: Mapped[list[Any]] = mapped_column(JSONB, default=list)
    decision: Mapped[str] = mapped_column(String, default="")
    consequences: Mapped[str] = mapped_column(String, default="")
    risk_summary: Mapped[str] = mapped_column(String, default="")
    risk_class: Mapped[str] = mapped_column(String(32), default="config_code_change")
    blast_radius: Mapped[str] = mapped_column(String(16), default="medium")
    gate_decision: Mapped[str] = mapped_column(String(32), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class ExecutionJob(Base):
    """A provider CLI operation tracked independently from chat output."""

    __tablename__ = "execution_jobs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    project_id: Mapped[str] = mapped_column(String(36), index=True)
    provider: Mapped[str] = mapped_column(String(16), index=True)
    operation: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    target: Mapped[str] = mapped_column(String(400), default="")
    access_scope: Mapped[str] = mapped_column(String(16), default="read_only")
    status: Mapped[str] = mapped_column(String(32), index=True, default="planned")
    requested_by: Mapped[str] = mapped_column(String(120), default="user")
    command_preview: Mapped[str] = mapped_column(String, default="")
    operation_hash: Mapped[str] = mapped_column(String(64), default="")
    result: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    error: Mapped[str] = mapped_column(String, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    queued_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)


class ExecutionEvent(Base):
    """Append-only lifecycle event or redacted CLI output for an action."""

    __tablename__ = "execution_events"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    action_id: Mapped[str] = mapped_column(String(36), index=True)
    event_type: Mapped[str] = mapped_column(String(32), index=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class ExecutionApproval(Base):
    """Approval bound to the exact structured operation hash."""

    __tablename__ = "execution_approvals"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    action_id: Mapped[str] = mapped_column(String(36), index=True)
    decision: Mapped[str] = mapped_column(String(16), default="pending")
    approver: Mapped[str] = mapped_column(String(120), default="")
    approved_operation_hash: Mapped[str] = mapped_column(String(64), default="")
    confirmation_count: Mapped[int] = mapped_column(default=0)
    decided_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
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


def _migrate() -> None:  # pragma: no cover
    """Bring pre-project databases up to the project-scoped schema (idempotent).

    This path only executes against legacy schemas that pre-date the current
    models. The live test database is created from current metadata, so the
    branches cannot be exercised without fabricating obsolete tables.
    """
    inspector = inspect(engine)
    tables = set(inspector.get_table_names())

    with engine.begin() as conn:
        if "projects" in tables:
            project_columns = {c["name"] for c in inspector.get_columns("projects")}
            # Older deployments may have created this table under a different
            # database role. Do not ALTER it during API startup. The existing
            # app_config table is writable by the application role and stores
            # the selected default without requiring table ownership.
            default_id = None
            if "is_default" in project_columns:
                default_id = conn.execute(
                    text(
                        "SELECT id FROM projects WHERE is_default = TRUE "
                        "ORDER BY created_at ASC, id ASC LIMIT 1"
                    )
                ).scalar()
            if default_id is None:
                default_id = conn.execute(
                    text(
                        "SELECT id FROM projects ORDER BY "
                        "CASE WHEN id = :default_id THEN 0 ELSE 1 END, "
                        "created_at ASC, id ASC LIMIT 1"
                    ),
                    {"default_id": DEFAULT_PROJECT_ID},
                ).scalar()
            if default_id is None:
                # Ensure the seeded org exists before inserting the default project.
                conn.execute(
                    text(
                        "INSERT INTO organizations (id, name, slug, created_by, created_at, updated_at) "
                        "VALUES (:id, :name, :slug, '', now(), now()) "
                        "ON CONFLICT (id) DO NOTHING"
                    ),
                    {
                        "id": DEFAULT_ORG_ID,
                        "name": "InfraLens",
                        "slug": DEFAULT_ORG_SLUG,
                    },
                )
                conn.execute(
                    text(
                        "INSERT INTO projects (id, org_id, name, repos, created_at, updated_at) "
                        "VALUES (:id, :org_id, :name, '[]'::jsonb, now(), now()) "
                        "ON CONFLICT (id) DO NOTHING"
                    ),
                    {
                        "id": DEFAULT_PROJECT_ID,
                        "org_id": DEFAULT_ORG_ID,
                        "name": "Default project",
                    },
                )
                default_id = DEFAULT_PROJECT_ID

            conn.execute(
                text(
                    "INSERT INTO app_config (key, value) VALUES (:key, :value) "
                    "ON CONFLICT (key) DO NOTHING"
                ),
                {"key": DEFAULT_PROJECT_CONFIG_KEY, "value": default_id},
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

        if "execution_approvals" in tables:
            approval_columns = {c["name"] for c in inspector.get_columns("execution_approvals")}
            if "confirmation_count" not in approval_columns:
                conn.execute(
                    text(
                        "ALTER TABLE execution_approvals "
                        "ADD COLUMN confirmation_count INTEGER NOT NULL DEFAULT 0"
                    )
                )

        if "users" in tables:
            user_columns = {c["name"] for c in inspector.get_columns("users")}
            if "role" not in user_columns:
                try:
                    conn.execute(
                        text(
                            "ALTER TABLE users ADD COLUMN role VARCHAR(32) "
                            "NOT NULL DEFAULT 'developer'"
                        )
                    )
                except Exception:
                    # Table may be owned by another role; create_all + seed still work
                    # for new DBs. Existing rows get role via ensure_seed_user upgrade.
                    pass
            if "email" not in user_columns:
                try:
                    conn.execute(
                        text(
                            "ALTER TABLE users ADD COLUMN email VARCHAR(255) "
                            "NOT NULL DEFAULT ''"
                        )
                    )
                except Exception:
                    pass

        if "projects" in tables:
            project_columns = {c["name"] for c in inspector.get_columns("projects")}
            if "org_id" not in project_columns:
                try:
                    conn.execute(
                        text(
                            "ALTER TABLE projects ADD COLUMN org_id VARCHAR(36) "
                            "NOT NULL DEFAULT ''"
                        )
                    )
                except Exception:
                    pass

        if "chat_memories" in tables:
            memory_columns = {c["name"] for c in inspector.get_columns("chat_memories")}
            for column, ddl in (
                ("requirements", "ADD COLUMN requirements JSONB NOT NULL DEFAULT '[]'::jsonb"),
                ("infra_state", "ADD COLUMN infra_state JSONB NOT NULL DEFAULT '{}'::jsonb"),
                (
                    "deployment_outcomes",
                    "ADD COLUMN deployment_outcomes JSONB NOT NULL DEFAULT '[]'::jsonb",
                ),
            ):
                if column not in memory_columns:
                    try:
                        conn.execute(text(f"ALTER TABLE chat_memories {ddl}"))
                    except Exception:
                        pass


def ensure_tenancy_seed() -> None:
    """Create default org, attach orphan projects, grant seed admin org+project access."""
    import uuid as _uuid

    from sqlalchemy import select as _select

    with SessionLocal() as session:
        org = session.scalar(
            _select(Organization).where(Organization.slug == DEFAULT_ORG_SLUG)
        )
        if org is None:
            org = Organization(
                id=DEFAULT_ORG_ID,
                name="InfraLens",
                slug=DEFAULT_ORG_SLUG,
                created_by="",
            )
            session.add(org)
            session.flush()
        # Ensure default org executor settings exist.
        if session.get(OrgExecutorSettings, org.id) is None:
            session.add(
                OrgExecutorSettings(
                    org_id=org.id,
                    mode="on_demand",
                    window_hours=12,
                    idle_scale_down_minutes=15,
                    max_replicas=1,
                )
            )

        for project in session.scalars(_select(Project)).all():
            if not (project.org_id or "").strip():
                project.org_id = org.id

        admin = session.scalar(
            _select(User).where(User.role == "super_admin").order_by(User.created_at.asc())
        )
        if admin is None:
            admin = session.scalar(_select(User).order_by(User.created_at.asc()).limit(1))
        if admin is not None:
            if not (admin.email or "").strip():
                admin.email = f"{admin.username}@local"
            org.created_by = org.created_by or admin.id
            existing_om = session.scalar(
                _select(OrgMembership).where(
                    OrgMembership.org_id == org.id,
                    OrgMembership.user_id == admin.id,
                )
            )
            if existing_om is None:
                session.add(
                    OrgMembership(
                        id=str(_uuid.uuid4()),
                        org_id=org.id,
                        user_id=admin.id,
                        org_role="org_admin",
                    )
                )
            for project in session.scalars(
                _select(Project).where(Project.org_id == org.id)
            ).all():
                existing_pm = session.scalar(
                    _select(ProjectMembership).where(
                        ProjectMembership.project_id == project.id,
                        ProjectMembership.user_id == admin.id,
                    )
                )
                if existing_pm is None:
                    session.add(
                        ProjectMembership(
                            id=str(_uuid.uuid4()),
                            project_id=project.id,
                            user_id=admin.id,
                            project_role="devops_lead",
                        )
                    )
        session.commit()


def init_db() -> None:
    """Create tables if they do not exist, then apply lightweight migrations."""
    Base.metadata.create_all(engine)
    _migrate()
    try:
        ensure_tenancy_seed()
    except Exception:
        # Seed may run before users exist on first boot; auth.ensure_seed_user retries.
        pass
