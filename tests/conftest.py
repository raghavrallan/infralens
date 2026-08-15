"""Shared pytest fixtures. Environment is configured before app imports."""
from __future__ import annotations

import os
import sys
import time
import uuid
from pathlib import Path

# ---------------------------------------------------------------------------
# Test environment — must run before `app.core.db` creates the SQLAlchemy engine.
# python-dotenv in app.main does not override existing variables.
# ---------------------------------------------------------------------------
os.environ.setdefault("AUTH_JWT_SECRET", "test-jwt-secret-not-for-production")
os.environ.setdefault("AUTH_USERNAME", "test-admin")
os.environ.setdefault("AUTH_PASSWORD", "test-password-12")
os.environ.setdefault("AUTH_DISPLAY_NAME", "Test Admin")
os.environ.setdefault("AUTH_VERIFY_DB", "false")
os.environ.setdefault("EXECUTOR_SERVICE_KEY", "test-executor-key")
os.environ.setdefault("LANGFUSE_TRACING_ENABLED", "false")
os.environ["LANGFUSE_PUBLIC_KEY"] = ""
os.environ["LANGFUSE_SECRET_KEY"] = ""
os.environ.setdefault("SMTP_HOST", "")

_DEFAULT_TEST_DB = (
    "postgresql+psycopg2://devsecops:devsecops@localhost:5544/devsecops_test"
)
if not os.environ.get("DATABASE_URL"):
    os.environ["DATABASE_URL"] = os.environ.get("TEST_DATABASE_URL", _DEFAULT_TEST_DB)

_ROOT = Path(__file__).resolve().parents[1]
_FRONTEND_OUT = _ROOT / "frontend" / "out"


def _ensure_frontend_export() -> None:
    """app.main mounts StaticFiles on frontend/out; tests need a stub tree."""
    pages = (
        "",
        "dashboard",
        "settings",
        "wiki",
        "login",
        "organizations",
        "onboarding",
        "accept-invite",
        "approve-member",
    )
    stub = "<!doctype html><title>test</title>"
    for page in pages:
        directory = _FRONTEND_OUT / page if page else _FRONTEND_OUT
        directory.mkdir(parents=True, exist_ok=True)
        target = directory / "index.html"
        if not target.exists():
            target.write_text(stub, encoding="utf-8")
    index = _FRONTEND_OUT / "index.html"
    if not index.exists():
        index.write_text(stub, encoding="utf-8")


_ensure_frontend_export()


def _ensure_test_database() -> bool:
    """Create the isolated test database when Postgres is reachable."""
    url = os.environ.get("DATABASE_URL", "")
    try:
        from sqlalchemy import create_engine, text
        from sqlalchemy.engine.url import make_url

        parsed = make_url(url)
        dbname = parsed.database or "devsecops_test"
        admin = parsed.set(database="postgres")
        engine = create_engine(admin, isolation_level="AUTOCOMMIT", future=True)
        with engine.connect() as conn:
            exists = conn.execute(
                text("SELECT 1 FROM pg_database WHERE datname = :n"),
                {"n": dbname},
            ).scalar()
            if not exists:
                conn.execute(text(f'CREATE DATABASE "{dbname}"'))
        engine.dispose()
        return True
    except Exception:
        return False


_ensure_test_database()

import pytest  # noqa: E402
import app.skills  # noqa: E402,F401 — load skills before architect graph (circular import)
import jwt  # noqa: E402


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line("markers", "unit: isolated tests")
    config.addinivalue_line("markers", "integration: requires PostgreSQL")
    config.addinivalue_line("markers", "e2e: critical-path workflows")


@pytest.fixture(scope="session")
def postgres_available() -> bool:
    if not _ensure_test_database():
        return False
    try:
        from sqlalchemy import create_engine, text

        engine = create_engine(os.environ["DATABASE_URL"], future=True)
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        engine.dispose()
        return True
    except Exception:
        return False


@pytest.fixture(scope="session")
def db_initialized(postgres_available: bool) -> bool:
    if not postgres_available:
        return False
    from app.core.db import init_db
    from app.core import auth

    init_db()
    auth.ensure_seed_user()
    return True


@pytest.fixture
def require_db(db_initialized: bool) -> None:
    if not db_initialized:
        pytest.skip("PostgreSQL test database is not available")


def _token_for(user: dict) -> str:
    from app.core.auth import JWT_ALGORITHM, TOKEN_TTL_SECONDS, _jwt_secret

    return jwt.encode(
        {
            "sub": user["id"],
            "username": user["username"],
            "name": user.get("name") or user["username"],
            "role": user["role"],
            "org_ids": user.get("org_ids") or [],
            "exp": int(time.time()) + TOKEN_TTL_SECONDS,
        },
        _jwt_secret(),
        algorithm=JWT_ALGORITHM,
    )


@pytest.fixture
def make_user(require_db):
    from app.core.auth import hash_password
    from app.core.db import SessionLocal, User

    created: list[str] = []

    def _factory(
        *,
        role: str = "developer",
        username: str | None = None,
        email: str | None = None,
        password: str = "secret12",
        is_active: bool = True,
    ) -> dict:
        uname = username or f"u_{uuid.uuid4().hex[:10]}"
        with SessionLocal() as session:
            row = User(
                id=str(uuid.uuid4()),
                username=uname,
                email=email or f"{uname}@example.com",
                display_name=uname,
                password_hash=hash_password(password),
                role=role,
                is_active=is_active,
            )
            session.add(row)
            session.commit()
            created.append(row.id)
            return {
                "id": row.id,
                "username": row.username,
                "name": row.display_name,
                "role": role,
                "email": row.email,
                "password": password,
                "token": _token_for(
                    {
                        "id": row.id,
                        "username": row.username,
                        "name": row.display_name,
                        "role": role,
                    }
                ),
            }

    yield _factory


@pytest.fixture
def auth_header(make_user):
    def _header(role: str = "developer", **kwargs) -> dict[str, str]:
        user = make_user(role=role, **kwargs)
        return {"Authorization": f"Bearer {user['token']}"}, user

    return _header


@pytest.fixture
def super_admin(make_user) -> dict:
    return make_user(role="super_admin")


@pytest.fixture
def org_admin(make_user) -> dict:
    return make_user(role="org_admin")


@pytest.fixture
def devops_lead(make_user) -> dict:
    return make_user(role="devops_lead")


@pytest.fixture
def devops_engineer(make_user) -> dict:
    return make_user(role="devops_engineer")


@pytest.fixture
def developer(make_user) -> dict:
    return make_user(role="developer")


@pytest.fixture
def viewer(make_user) -> dict:
    return make_user(role="viewer")


def _bearer(user: dict) -> dict[str, str]:
    return {"Authorization": f"Bearer {user['token']}"}


@pytest.fixture
def client(db_initialized: bool):
    """FastAPI TestClient with background jobs disabled."""
    if not db_initialized:
        pytest.skip("PostgreSQL test database is not available")
    from unittest.mock import patch

    from fastapi.testclient import TestClient

    with (
        patch("app.intelligence.scheduler.start_scheduler"),
        patch("app.intelligence.scheduler.shutdown_scheduler"),
        patch("app.org_executors.controller.start_controller"),
        patch("app.org_executors.controller.stop_controller"),
        patch("app.core.prompts.seed_core_prompts"),
        patch("app.agents.solution_architect.graph.setup_checkpointer"),
    ):
        from app.main import app

        with TestClient(app) as test_client:
            yield test_client


@pytest.fixture
def org_with_project(require_db, super_admin):
    from app.tenancy import memberships, orgs, projects

    org = orgs.create_org(
        name=f"TestOrg-{uuid.uuid4().hex[:6]}", created_by=super_admin["id"]
    )
    project = projects.create_project(
        f"TestProj-{uuid.uuid4().hex[:6]}",
        org_id=org["id"],
        owner_user_id=super_admin["id"],
        owner_project_role="devops_lead",
    )
    memberships.ensure_org_membership(
        org_id=org["id"], user_id=super_admin["id"], org_role="org_admin"
    )
    return {"org": org, "project": project, "admin": super_admin}


# Silence unused import of sys on some platforms (kept for path debugging).
_ = sys
