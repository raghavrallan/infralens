"""Onboarding wizard APIs: status, complete (existing vs new GitHub repo)."""
from __future__ import annotations

from typing import Any, Literal, Optional

from app.tenancy import (
    memberships,
    projects,
)
from app.platform import connections
from app.providers import github_infra
from app.core.rbac import normalize_role


def status(*, user: dict[str, Any]) -> dict[str, Any]:
    """Per-user onboarding: needs wizard when the user has no accessible projects
    (or none of their projects have mapped repos yet and they have zero memberships).
    """
    accessible = projects.list_projects(user=user)
    has_mapped_repos = any(projects.get_repos(p["id"]) for p in accessible)
    # New invited users: org membership but zero projects → must onboard.
    needs = len(accessible) == 0 or not has_mapped_repos
    # Super Admin who already has mapped projects should not be forced.
    if accessible and has_mapped_repos:
        needs = False
    return {
        "needs_onboarding": needs,
        "project_count": len(accessible),
        "org_id": memberships.primary_org_id(user),
        "user": {
            "id": user.get("id"),
            "username": user.get("username"),
            "name": user.get("name"),
            "role": user.get("role"),
        },
        "paths": [
            {
                "id": "existing",
                "label": "Use existing GitHub repository",
                "description": "Connect GitHub, pick a repo, optionally connect Azure.",
            },
            {
                "id": "new",
                "label": "Create a new GitHub repository",
                "description": "Create a repo on your account, then link an InfraLens project.",
            },
        ],
    }


def complete(
    *,
    path: Literal["existing", "new"],
    project_name: str,
    repos: list[str],
    user: dict[str, Any],
    azure_connected: bool = False,
    github_connected: bool = False,
    project_id: Optional[str] = None,
    org_id: Optional[str] = None,
) -> dict[str, Any]:
    name = (project_name or "").strip() or "New project"
    clean_repos = [r.strip() for r in repos if isinstance(r, str) and r.strip()]
    if path == "existing" and not clean_repos:
        raise ValueError("Select at least one GitHub repository")
    if path == "new" and not clean_repos:
        raise ValueError("Create or provide the new repository full name (owner/name)")

    target_org = org_id or memberships.ensure_user_org(user)
    memberships.assert_org_access(user, target_org)

    owner_id = str(user.get("id") or "")
    role = normalize_role(user.get("role"))
    project_role = (
        "devops_lead"
        if role in {"super_admin", "org_admin", "devops_lead"}
        else ("devops_engineer" if role == "devops_engineer" else "developer")
    )

    if project_id and projects.get_project(project_id):
        memberships.assert_project_access(user, project_id)
        projects.rename_project(project_id, name)
        project = projects.get_project(project_id) or {"id": project_id, "name": name}
    else:
        project = projects.create_project(
            name,
            org_id=target_org,
            owner_user_id=owner_id or None,
            owner_project_role=project_role,
            reuse_empty=True,
        )
        project_id = project["id"]

    if clean_repos:
        projects.set_repos(project_id, clean_repos)
        project = projects.get_project(project_id) or project

    if owner_id:
        memberships.ensure_project_membership(
            project_id=project_id,
            user_id=owner_id,
            project_role=project_role,
        )

    # Drop empty twin projects from double ensureProject / remounts.
    projects.collapse_duplicate_empty_projects(
        user=user, keep_project_id=project_id, org_id=target_org
    )

    github_status = connections.status(project_id, "github")
    azure_status = connections.status(project_id, "azure")
    return {
        "ok": True,
        "path": path,
        "project": project,
        "github_connected": bool(github_status.get("connected") or github_connected),
        "azure_connected": bool(azure_status.get("connected") or azure_connected),
        "next": "delivery" if path == "new" else "dashboard",
    }


def github_identity(project_id: str) -> dict[str, Any]:
    creds = github_infra.load_credentials(project_id)
    with github_infra._client(creds) as client:
        resp = github_infra._get(client, "/user")
        if resp.status_code >= 400:
            raise github_infra.GitHubApiError(
                f"GitHub identity check failed: {github_infra._error_detail(resp)}"
            )
        body = resp.json()
    return {
        "login": body.get("login"),
        "name": body.get("name"),
        "id": body.get("id"),
        "html_url": body.get("html_url"),
    }
