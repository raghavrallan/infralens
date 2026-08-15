"""Organization CRUD — Super Admin creates orgs; members list their orgs."""
from __future__ import annotations

import re
import uuid
from typing import Any, Optional

from sqlalchemy import func, select

from app.tenancy import memberships
from app.core.db import Organization, OrgMembership, Project, SessionLocal, User
from app.core.rbac import normalize_role


def _slugify(name: str) -> str:
    base = re.sub(r"[^a-z0-9]+", "-", (name or "").strip().lower()).strip("-")
    return (base or "org")[:100]


def _public(
    org: Organization, *, member_count: int = 0, project_count: int = 0
) -> dict[str, Any]:
    return {
        "id": org.id,
        "name": org.name,
        "slug": org.slug,
        "created_by": org.created_by,
        "member_count": member_count,
        "project_count": project_count,
        "created_at": org.created_at.isoformat() if org.created_at else None,
        "updated_at": org.updated_at.isoformat() if org.updated_at else None,
    }


def get_org(org_id: str) -> Optional[dict[str, Any]]:
    with SessionLocal() as session:
        org = session.get(Organization, org_id)
        if org is None:
            return None
        member_count = session.scalar(
            select(func.count()).select_from(OrgMembership).where(
                OrgMembership.org_id == org_id
            )
        ) or 0
        project_count = session.scalar(
            select(func.count()).select_from(Project).where(Project.org_id == org_id)
        ) or 0
        return _public(org, member_count=int(member_count), project_count=int(project_count))


def list_orgs_for_user(user: dict[str, Any]) -> list[dict[str, Any]]:
    with SessionLocal() as session:
        if memberships.is_super_admin(user):
            orgs = list(session.scalars(select(Organization).order_by(Organization.name.asc())).all())
        else:
            org_ids = memberships.user_org_ids(str(user.get("id") or ""))
            if not org_ids:
                return []
            orgs = list(
                session.scalars(
                    select(Organization)
                    .where(Organization.id.in_(org_ids))
                    .order_by(Organization.name.asc())
                ).all()
            )
        out: list[dict[str, Any]] = []
        for org in orgs:
            member_count = session.scalar(
                select(func.count()).select_from(OrgMembership).where(
                    OrgMembership.org_id == org.id
                )
            ) or 0
            project_count = session.scalar(
                select(func.count()).select_from(Project).where(Project.org_id == org.id)
            ) or 0
            out.append(
                _public(org, member_count=int(member_count), project_count=int(project_count))
            )
        return out


def create_org(
    *,
    name: str,
    created_by: str,
    org_admin_user_id: Optional[str] = None,
    slug: Optional[str] = None,
) -> dict[str, Any]:
    clean = " ".join((name or "").strip().split())
    if not clean:
        raise ValueError("Organization name is required")
    base_slug = _slugify(slug or clean)
    with SessionLocal() as session:
        candidate = base_slug
        n = 1
        while session.scalar(select(Organization.id).where(Organization.slug == candidate)):
            n += 1
            candidate = f"{base_slug}-{n}"
        org = Organization(
            id=str(uuid.uuid4()),
            name=clean[:120],
            slug=candidate,
            created_by=created_by,
        )
        session.add(org)
        session.flush()
        admin_id = org_admin_user_id or created_by
        if admin_id:
            session.add(
                OrgMembership(
                    id=str(uuid.uuid4()),
                    org_id=org.id,
                    user_id=admin_id,
                    org_role="org_admin",
                )
            )
            # Do not overwrite an invited global role (e.g. devops_lead).
            # Org power comes from org_membership.org_role.
        session.commit()
        result = _public(org, member_count=1 if admin_id else 0, project_count=0)
    try:
        from app.org_executors import settings as org_executor_settings

        org_executor_settings.ensure_settings(result["id"])
    except Exception:
        pass
    return result


def assign_org_admin(*, org_id: str, user_id: str) -> dict[str, Any]:
    with SessionLocal() as session:
        org = session.get(Organization, org_id)
        if org is None:
            raise LookupError("Organization not found")
        user = session.get(User, user_id)
        if user is None:
            raise LookupError("User not found")
        if normalize_role(user.role) != "super_admin":
            user.role = "org_admin"
    return memberships.ensure_org_membership(
        org_id=org_id, user_id=user_id, org_role="org_admin"
    )


def list_org_projects(org_id: str) -> list[dict[str, Any]]:
    from app.tenancy import projects as projects_mod

    # Soft-clean empty duplicate shells left from onboarding retries.
    with SessionLocal() as session:
        rows = list(
            session.scalars(
                select(Project).where(Project.org_id == org_id).order_by(Project.created_at.asc())
            ).all()
        )
        by_name: dict[str, list[Project]] = {}
        for p in rows:
            key = (p.name or "").strip().lower()
            by_name.setdefault(key, []).append(p)
        for group in by_name.values():
            if len(group) < 2:
                continue
            with_repos = [p for p in group if p.repos]
            keep = with_repos[-1] if with_repos else group[-1]
            for p in group:
                if p.id == keep.id:
                    continue
                if p.repos:
                    continue
                projects_mod.delete_project(p.id)

    with SessionLocal() as session:
        rows = session.scalars(
            select(Project).where(Project.org_id == org_id).order_by(Project.created_at.asc())
        ).all()
        return [
            {
                "id": p.id,
                "name": p.name,
                "org_id": p.org_id,
                "repos": list(p.repos or []),
                "created_at": p.created_at.isoformat() if p.created_at else None,
            }
            for p in rows
        ]
