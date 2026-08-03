#!/usr/bin/env python3
"""Seed shared admin + InfraLens org + EQIP project (with Azure/GitHub).

Idempotent. Copies the EQIP Azure SP + GitHub token used on the source machine
so a fresh Docker host can log in and use live connections without Settings setup.

Examples:

  .\\start-local.ps1 seed -ResetPassword

  docker compose --profile container-app exec api \\
    python scripts/seed_shared_tenant.py --reset-password

  AUTH_USERNAME=admin AUTH_PASSWORD=infralens \\
    python scripts/seed_shared_tenant.py --reset-password
"""
from __future__ import annotations

import argparse
import os
import sys
import uuid
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from sqlalchemy import select

from app import auth, connections, memberships, orgs, projects
from app.db import (
    DEFAULT_ORG_ID,
    DEFAULT_ORG_SLUG,
    Organization,
    OrgExecutorSettings,
    Project,
    SessionLocal,
    User,
    ensure_tenancy_seed,
    init_db,
)
from app.org_executors import settings as org_executor_settings

SEED_ORG_ID = os.environ.get("SEED_ORG_ID", DEFAULT_ORG_ID).strip() or DEFAULT_ORG_ID
SEED_ORG_SLUG = os.environ.get("SEED_ORG_SLUG", DEFAULT_ORG_SLUG).strip() or DEFAULT_ORG_SLUG
SEED_ORG_NAME = os.environ.get("SEED_ORG_NAME", "InfraLens").strip() or "InfraLens"
SEED_PROJECT_ID = (
    os.environ.get("SEED_PROJECT_ID", "5310f26d-911a-47f6-b7ab-4376d8ab78bd").strip()
    or "5310f26d-911a-47f6-b7ab-4376d8ab78bd"
)
SEED_PROJECT_NAME = os.environ.get("SEED_PROJECT_NAME", "EQIP").strip() or "EQIP"

# Source EQIP connections (override with SEED_AZURE_* / SEED_GITHUB_* env vars).
DEFAULT_AZURE = {
    "tenant_id": "2d31dd2c-1d9b-47f2-90d1-48a747ccae92",
    "client_id": "9adf4760-ea7a-4d58-aa5b-9d348f58f07a",
    "client_secret": "JwU8Q~idBjkUpD90AecTcZjE_mu9-.EZVkKkwad8",
    "subscription_id": "652ec4ff-164e-46ad-a0f8-02e458fc6baf",
}
DEFAULT_GITHUB = {
    "token": "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",
    "username": "raghavrallan",
}
DEFAULT_REPOS = ["acme/admin-repo"]


def _env_username(cli: str | None) -> str:
    return (cli or os.environ.get("AUTH_USERNAME") or auth.DEFAULT_USERNAME).strip()


def _env_password(cli: str | None) -> str:
    return cli or os.environ.get("AUTH_PASSWORD") or auth.DEFAULT_PASSWORD


def _env_display_name(cli: str | None) -> str:
    return (
        (cli or os.environ.get("AUTH_DISPLAY_NAME") or auth.DEFAULT_DISPLAY_NAME).strip()
        or auth.DEFAULT_DISPLAY_NAME
    )


def _azure_fields() -> dict[str, str]:
    return {
        "tenant_id": os.environ.get("SEED_AZURE_TENANT_ID", DEFAULT_AZURE["tenant_id"]),
        "client_id": os.environ.get("SEED_AZURE_CLIENT_ID", DEFAULT_AZURE["client_id"]),
        "client_secret": os.environ.get(
            "SEED_AZURE_CLIENT_SECRET", DEFAULT_AZURE["client_secret"]
        ),
        "subscription_id": os.environ.get(
            "SEED_AZURE_SUBSCRIPTION_ID", DEFAULT_AZURE["subscription_id"]
        ),
    }


def _github_fields() -> dict[str, str]:
    return {
        "token": os.environ.get("SEED_GITHUB_TOKEN", DEFAULT_GITHUB["token"]),
        "username": os.environ.get("SEED_GITHUB_USERNAME", DEFAULT_GITHUB["username"]),
    }


def _seed_repos() -> list[str]:
    raw = (os.environ.get("SEED_PROJECT_REPOS") or "").strip()
    if raw:
        return [item.strip() for item in raw.split(",") if item.strip()]
    return list(DEFAULT_REPOS)


def ensure_admin(
    *,
    username: str,
    password: str,
    display_name: str,
    reset_password: bool,
) -> dict[str, Any]:
    auth.ensure_seed_user()
    with SessionLocal() as session:
        user = session.scalar(select(User).where(User.username == username))
        if user is None:
            user = User(
                id=str(uuid.uuid4()),
                username=username,
                email=f"{username}@local",
                display_name=display_name,
                password_hash=auth.hash_password(password),
                role="super_admin",
                is_active=True,
            )
            session.add(user)
            session.commit()
            session.refresh(user)
            return {
                "id": user.id,
                "username": user.username,
                "created": True,
                "password_reset": True,
            }

        changed = False
        if (user.role or "") != "super_admin":
            user.role = "super_admin"
            changed = True
        if not (user.display_name or "").strip():
            user.display_name = display_name
            changed = True
        if not (user.email or "").strip():
            user.email = f"{username}@local"
            changed = True
        password_reset = False
        if reset_password or not user.password_hash:
            user.password_hash = auth.hash_password(password)
            password_reset = True
            changed = True
        if changed:
            session.commit()
        return {
            "id": user.id,
            "username": user.username,
            "created": False,
            "password_reset": password_reset,
        }


def ensure_org(*, admin_user_id: str) -> dict[str, Any]:
    with SessionLocal() as session:
        by_id = session.get(Organization, SEED_ORG_ID)
        by_slug = session.scalar(
            select(Organization).where(Organization.slug == SEED_ORG_SLUG)
        )
        if by_id is None and by_slug is None:
            session.add(
                Organization(
                    id=SEED_ORG_ID,
                    name=SEED_ORG_NAME,
                    slug=SEED_ORG_SLUG,
                    created_by=admin_user_id,
                )
            )
            session.commit()
            created = True
            org_id = SEED_ORG_ID
        elif by_id is not None:
            created = False
            org_id = by_id.id
            if (by_id.name or "").strip() != SEED_ORG_NAME:
                by_id.name = SEED_ORG_NAME
                session.commit()
        else:
            created = False
            assert by_slug is not None
            org_id = by_slug.id
            if (by_slug.name or "").strip() != SEED_ORG_NAME:
                by_slug.name = SEED_ORG_NAME
                session.commit()

    memberships.ensure_org_membership(
        org_id=org_id, user_id=admin_user_id, org_role="org_admin"
    )
    org_executor_settings.ensure_settings(org_id)
    row = orgs.get_org(org_id) or {
        "id": org_id,
        "name": SEED_ORG_NAME,
        "slug": SEED_ORG_SLUG,
    }
    return {**row, "created": created}


def ensure_eqip_project(*, org_id: str, admin_user_id: str) -> dict[str, Any]:
    repos = _seed_repos()
    with SessionLocal() as session:
        existing = session.get(Project, SEED_PROJECT_ID)
        if existing is None:
            by_name = session.scalar(
                select(Project).where(
                    Project.org_id == org_id,
                    Project.name == SEED_PROJECT_NAME,
                )
            )
            if by_name is not None:
                project_id = by_name.id
                created = False
                by_name.org_id = org_id
                by_name.name = SEED_PROJECT_NAME
                if repos and not (by_name.repos or []):
                    by_name.repos = repos
                session.commit()
            else:
                session.add(
                    Project(
                        id=SEED_PROJECT_ID,
                        name=SEED_PROJECT_NAME,
                        org_id=org_id,
                        repos=repos,
                    )
                )
                session.commit()
                project_id = SEED_PROJECT_ID
                created = True
        else:
            created = False
            project_id = existing.id
            if (existing.org_id or "").strip() != org_id:
                existing.org_id = org_id
            if (existing.name or "").strip() != SEED_PROJECT_NAME:
                existing.name = SEED_PROJECT_NAME
            if repos and not (existing.repos or []):
                existing.repos = repos
            session.commit()

    memberships.ensure_project_membership(
        project_id=project_id,
        user_id=admin_user_id,
        project_role="devops_lead",
    )
    summary = projects.get_project(project_id) or {
        "id": project_id,
        "name": SEED_PROJECT_NAME,
        "org_id": org_id,
        "repos": repos,
    }
    return {**summary, "created": created}


def ensure_connections(*, project_id: str) -> dict[str, Any]:
    azure = connections.set_connection(
        project_id, "azure", "client_secret", _azure_fields()
    )
    github = connections.set_connection(project_id, "github", "token", _github_fields())
    return {"azure": azure, "github": github}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Seed shared admin + InfraLens + EQIP with Azure/GitHub connections."
    )
    parser.add_argument("--username", default=None)
    parser.add_argument("--password", default=None)
    parser.add_argument("--display-name", default=None)
    parser.add_argument(
        "--reset-password",
        action="store_true",
        help="Reset admin password even if the user already exists",
    )
    parser.add_argument(
        "--skip-connections",
        action="store_true",
        help="Do not write Azure/GitHub connection secrets",
    )
    args = parser.parse_args(argv)

    username = _env_username(args.username)
    password = _env_password(args.password)
    display_name = _env_display_name(args.display_name)

    init_db()
    ensure_tenancy_seed()

    admin = ensure_admin(
        username=username,
        password=password,
        display_name=display_name,
        reset_password=bool(args.reset_password),
    )
    org = ensure_org(admin_user_id=admin["id"])
    project = ensure_eqip_project(org_id=org["id"], admin_user_id=admin["id"])
    conn_status: dict[str, Any] = {}
    if not args.skip_connections:
        conn_status = ensure_connections(project_id=project["id"])

    with SessionLocal() as session:
        has_settings = session.get(OrgExecutorSettings, org["id"]) is not None

    print("Shared tenant seed complete")
    print(f"  admin.username     = {admin['username']}")
    print(f"  admin.id           = {admin['id']}")
    print(f"  admin.created      = {admin['created']}")
    print(f"  admin.password_set = {admin['password_reset'] or admin['created']}")
    if admin["password_reset"] or admin["created"]:
        print(f"  admin.password     = {password}")
    print(f"  org.name           = {org.get('name')}")
    print(f"  org.slug           = {org.get('slug')}")
    print(f"  org.id             = {org['id']}")
    print(f"  org.created        = {org['created']}")
    print(f"  project.name       = {project.get('name')}")
    print(f"  project.id         = {project['id']}")
    print(f"  project.org_id     = {project.get('org_id')}")
    print(f"  project.repos      = {project.get('repos')}")
    print(f"  project.created    = {project['created']}")
    print(f"  executor_settings  = {has_settings}")
    if conn_status:
        print(
            f"  azure.connected    = {bool((conn_status.get('azure') or {}).get('connected'))}"
        )
        print(
            f"  github.connected   = {bool((conn_status.get('github') or {}).get('connected'))}"
        )
        print(f"  github.username    = {_github_fields().get('username')}")
        print(f"  azure.subscription = {_azure_fields().get('subscription_id')}")
    print()
    print(
        "Login with the admin credentials above, then open "
        "Organizations > InfraLens / project EQIP."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
