"""Role-based access control for InfraLens.

Hierarchy (highest privilege first):
  super_admin > org_admin > devops_lead > devops_engineer > developer > viewer
"""
from __future__ import annotations

from typing import Any, Optional

from fastapi import Depends, Header, HTTPException, Request

ROLE_ORDER: tuple[str, ...] = (
    "viewer",
    "developer",
    "devops_engineer",
    "devops_lead",
    "org_admin",
    "super_admin",
)

ROLE_LABELS: dict[str, str] = {
    "super_admin": "Super Admin",
    "org_admin": "Org Admin",
    "devops_lead": "DevOps Lead",
    "devops_engineer": "DevOps Engineer",
    "developer": "Developer",
    "viewer": "Viewer",
}

CAPABILITY_MIN_ROLE: dict[str, str] = {
    "read": "viewer",
    "chat": "developer",
    "propose_write": "developer",
    "create_project": "developer",
    "connect_provider": "developer",
    "create_github_repo": "developer",
    "approve_human": "devops_engineer",
    "run_workflow": "devops_engineer",
    "run_architecture": "devops_lead",
    "verify_memory": "devops_engineer",
    "archive_memory": "devops_lead",
    "approve_two_person": "devops_lead",
    "prod_apply": "devops_lead",
    "break_glass": "devops_lead",
    "manage_users": "org_admin",
    "invite_users": "org_admin",
    "approve_membership": "org_admin",
    "manage_org": "org_admin",
    "create_org": "super_admin",
    "delete_project": "org_admin",
    "system_settings": "super_admin",
}

GATE_MIN_ROLE: dict[str, str] = {
    "autonomous": "developer",
    "autonomous_logged": "developer",
    "auto_instant_undo": "developer",
    "auto_apply": "devops_engineer",
    "human_approval": "devops_engineer",
    "two_person": "devops_lead",
}


def normalize_role(role: Optional[str]) -> str:
    value = (role or "developer").strip().lower().replace(" ", "_").replace("-", "_")
    aliases = {
        "admin": "super_admin",
        "superadmin": "super_admin",
        "orgadmin": "org_admin",
        "lead": "devops_lead",
        "engineer": "devops_engineer",
        "dev": "developer",
        "readonly": "viewer",
        "read_only": "viewer",
    }
    value = aliases.get(value, value)
    return value if value in ROLE_LABELS else "developer"


def role_rank(role: Optional[str]) -> int:
    try:
        return ROLE_ORDER.index(normalize_role(role))
    except ValueError:
        return 0


def has_min_role(user_role: Optional[str], minimum: str) -> bool:
    return role_rank(user_role) >= role_rank(minimum)


def can(user: dict[str, Any], capability: str) -> bool:
    minimum = CAPABILITY_MIN_ROLE.get(capability, "super_admin")
    return has_min_role(user.get("role"), minimum)


def can_approve_gate(user: dict[str, Any], gate: str) -> bool:
    minimum = GATE_MIN_ROLE.get(gate, "devops_lead")
    return has_min_role(user.get("role"), minimum)


def _current_user(
    request: Request,
    authorization: Optional[str] = Header(default=None),
) -> dict[str, Any]:
    from app.core import auth

    return auth.require_user(request, authorization)


def require_capability(capability: str):
    """FastAPI dependency factory: require a capability for the current user."""

    def _dep(user: dict[str, Any] = Depends(_current_user)) -> dict[str, Any]:
        if not can(user, capability):
            raise HTTPException(
                status_code=403,
                detail=f"Requires {ROLE_LABELS.get(CAPABILITY_MIN_ROLE.get(capability, ''), 'higher')} role or above",
            )
        return user

    return _dep


def require_min_role(minimum: str):
    def _dep(user: dict[str, Any] = Depends(_current_user)) -> dict[str, Any]:
        if not has_min_role(user.get("role"), minimum):
            raise HTTPException(
                status_code=403,
                detail=f"Requires {ROLE_LABELS.get(normalize_role(minimum), minimum)} role or above",
            )
        return user

    return _dep


def assert_capability(user: dict[str, Any], capability: str) -> None:
    if not can(user, capability):
        raise HTTPException(
            status_code=403,
            detail=f"Requires {ROLE_LABELS.get(CAPABILITY_MIN_ROLE.get(capability, ''), 'higher')} role or above",
        )


def public_roles() -> list[dict[str, str]]:
    return [{"id": key, "label": label} for key, label in ROLE_LABELS.items()]
