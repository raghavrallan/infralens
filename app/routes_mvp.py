"""MVP platform routes: RBAC users, onboarding, OAuth, delivery, break-glass, actuators."""
from __future__ import annotations

from typing import Any, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from pydantic import BaseModel

from app import (
    auth,
    break_glass,
    connections,
    delivery,
    invites,
    mailer,
    membership_requests,
    memberships,
    memory,
    module_actuators,
    oauth_providers,
    onboarding,
    orgs,
    projects,
    users_admin,
)
from app.db import DEFAULT_PROJECT_ID
from app.providers import github_infra
from app.rbac import (
    assert_capability,
    can_approve_gate,
    public_roles,
    require_capability,
    require_min_role,
)

router = APIRouter()


class UserCreateRequest(BaseModel):
    username: str
    password: str
    display_name: str = ""
    role: str = "developer"


class UserPatchRequest(BaseModel):
    role: Optional[str] = None
    is_active: Optional[bool] = None
    display_name: Optional[str] = None
    password: Optional[str] = None


class OnboardingCompleteRequest(BaseModel):
    path: Literal["existing", "new"]
    project_name: str
    repos: list[str] = []
    azure_connected: bool = False
    github_connected: bool = False
    project_id: Optional[str] = None


class GitHubConnectPATRequest(BaseModel):
    project_id: str = DEFAULT_PROJECT_ID
    username: str = ""
    token: str
    org: str = ""


class AzureConnectSecretsRequest(BaseModel):
    project_id: str = DEFAULT_PROJECT_ID
    tenant_id: str
    client_id: str
    client_secret: str
    subscription_id: str = ""


class GitHubCreateRepoRequest(BaseModel):
    project_id: str = DEFAULT_PROJECT_ID
    name: str
    private: bool = True
    org: str = ""
    description: str = ""


class BreakGlassOpenRequest(BaseModel):
    project_id: str = DEFAULT_PROJECT_ID
    reason: str
    ttl_minutes: int = 60


class DeliveryCreateRequest(BaseModel):
    project_id: str = DEFAULT_PROJECT_ID


class DeliveryDocsRequest(BaseModel):
    docs: str


class DeliveryTransitionRequest(BaseModel):
    to_stage: str
    artifact_key: Optional[str] = None
    artifact_value: Any = None


class ActuatorRequest(BaseModel):
    project_id: str = DEFAULT_PROJECT_ID
    finding: dict[str, Any] = {}
    mode: str = ""
    tier: str = ""
    environment: str = "dev"


@router.get("/api/roles")
def list_roles() -> list[dict[str, str]]:
    return public_roles()


@router.get("/api/users")
def list_users(
    org_id: Optional[str] = None,
    user: dict[str, Any] = Depends(auth.require_user),
) -> list[dict[str, Any]]:
    target = org_id or memberships.primary_org_id(user)
    if memberships.is_super_admin(user):
        return users_admin.list_users(org_id=target, actor=user)
    if target and memberships.is_org_admin(user, target):
        return users_admin.list_users(org_id=target, actor=user)
    if memberships.user_is_org_admin_anywhere(user):
        return users_admin.list_users(org_id=target or memberships.primary_org_id(user), actor=user)
    raise HTTPException(status_code=403, detail="Org Admin required")


@router.post("/api/users")
def create_user(
    body: UserCreateRequest,
    org_id: Optional[str] = None,
    user: dict[str, Any] = Depends(auth.require_user),
) -> dict[str, Any]:
    target_org = org_id or memberships.primary_org_id(user)
    if not target_org:
        raise HTTPException(status_code=400, detail="Organization required")
    if not memberships.is_org_admin(user, target_org):
        raise HTTPException(status_code=403, detail="Org Admin required")
    try:
        return users_admin.create_user(
            username=body.username,
            password=body.password,
            display_name=body.display_name,
            role=body.role,
            org_id=target_org,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.patch("/api/users/{user_id}")
def patch_user(
    user_id: str,
    body: UserPatchRequest,
    _user: dict[str, Any] = Depends(require_capability("manage_users")),
) -> dict[str, Any]:
    try:
        return users_admin.update_user(
            user_id,
            role=body.role,
            is_active=body.is_active,
            display_name=body.display_name,
            password=body.password,
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/api/onboarding/status")
def onboarding_status(
    user: dict[str, Any] = Depends(auth.require_user),
) -> dict[str, Any]:
    return onboarding.status(user=user)


@router.post("/api/onboarding/complete")
def onboarding_complete(
    body: OnboardingCompleteRequest,
    user: dict[str, Any] = Depends(auth.require_user),
) -> dict[str, Any]:
    assert_capability(user, "create_project")
    try:
        return onboarding.complete(
            path=body.path,
            project_name=body.project_name,
            repos=body.repos,
            user=user,
            azure_connected=body.azure_connected,
            github_connected=body.github_connected,
            project_id=body.project_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except HTTPException:
        raise


@router.get("/api/providers/auth-options")
def provider_auth_options() -> dict[str, Any]:
    return oauth_providers.auth_options()


@router.post("/api/providers/github/pat")
def connect_github_pat(
    body: GitHubConnectPATRequest,
    user: dict[str, Any] = Depends(auth.require_user),
) -> dict[str, Any]:
    assert_capability(user, "connect_provider")
    if not body.token.strip():
        raise HTTPException(status_code=400, detail="Token is required")
    # Ensure project exists for wizard (may use default or temp project).
    if projects.get_project(body.project_id) is None:
        raise HTTPException(status_code=404, detail="Project not found")
    status = connections.set_connection(
        body.project_id,
        "github",
        "token",
        {
            "username": body.username,
            "token": body.token,
            "org": body.org,
        },
    )
    try:
        identity = onboarding.github_identity(body.project_id)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=f"GitHub validation failed: {exc}") from exc
    return {"connection": status, "identity": identity}


@router.post("/api/providers/azure/secrets")
def connect_azure_secrets(
    body: AzureConnectSecretsRequest,
    user: dict[str, Any] = Depends(auth.require_user),
) -> dict[str, Any]:
    assert_capability(user, "connect_provider")
    if projects.get_project(body.project_id) is None:
        raise HTTPException(status_code=404, detail="Project not found")
    status = connections.set_connection(
        body.project_id,
        "azure",
        "client_secret",
        {
            "tenant_id": body.tenant_id,
            "client_id": body.client_id,
            "client_secret": body.client_secret,
            "subscription_id": body.subscription_id,
        },
    )
    from app.intelligence import workflows as intel_wf
    from app.intelligence import scheduler as intel_scheduler

    enabled = intel_wf.enable_workflows_when_ready(body.project_id)
    if enabled:
        intel_scheduler.sync_schedules()
    return {"connection": status}


@router.get("/api/providers/github/oauth/start")
def github_oauth_start(
    request: Request,
    project_id: str = DEFAULT_PROJECT_ID,
    return_to: str = "onboarding",
    user: dict[str, Any] = Depends(auth.require_user),
) -> dict[str, Any]:
    assert_capability(user, "connect_provider")
    memberships.ensure_user_org(user)
    try:
        return oauth_providers.start_github_oauth(
            project_id=project_id,
            request_base=str(request.base_url),
            return_to=return_to,
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/api/providers/github/oauth/callback")
def github_oauth_callback(
    request: Request,
    code: str = "",
    state: str = "",
) -> RedirectResponse:
    frontend = (
        __import__("os").environ.get("PUBLIC_APP_URL")
        or "http://127.0.0.1:3000"
    ).rstrip("/")
    try:
        result = oauth_providers.finish_github_oauth(
            code=code, state=state, request_base=str(request.base_url)
        )
        return RedirectResponse(
            url=result.get("frontend_redirect")
            or f"{frontend}/onboarding?oauth=github&ok=1&project_id={result['project_id']}",
            status_code=302,
        )
    except Exception:
        return RedirectResponse(
            url=f"{frontend}/onboarding?oauth=github&ok=0",
            status_code=302,
        )


@router.get("/api/providers/azure/oauth/start")
def azure_oauth_start(
    request: Request,
    project_id: str = DEFAULT_PROJECT_ID,
    user: dict[str, Any] = Depends(auth.require_user),
) -> dict[str, Any]:
    assert_capability(user, "connect_provider")
    try:
        return oauth_providers.start_azure_oauth(
            project_id=project_id,
            request_base=str(request.base_url),
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/api/providers/azure/oauth/callback")
def azure_oauth_callback(
    request: Request,
    code: str = "",
    state: str = "",
) -> RedirectResponse:
    try:
        result = oauth_providers.finish_azure_oauth(
            code=code, state=state, request_base=str(request.base_url)
        )
        project_id = result["project_id"]
        return RedirectResponse(
            url=f"/settings?oauth=azure&ok=1&project_id={project_id}",
            status_code=302,
        )
    except Exception:
        return RedirectResponse(url="/settings?oauth=azure&ok=0", status_code=302)


@router.get("/api/github/repos")
def list_github_repos(
    project_id: str = DEFAULT_PROJECT_ID,
    user: dict[str, Any] = Depends(auth.require_user),
) -> list[dict[str, Any]]:
    assert_capability(user, "create_project")
    try:
        return github_infra.list_repos_for_picker(project_id)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/api/github/repos")
def create_github_repo(
    body: GitHubCreateRepoRequest,
    user: dict[str, Any] = Depends(auth.require_user),
) -> dict[str, Any]:
    assert_capability(user, "create_github_repo")
    try:
        return github_infra.create_repo(
            body.project_id,
            name=body.name,
            private=body.private,
            org=body.org or None,
            description=body.description,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/api/memory/precedent")
def list_precedent(
    project_id: str = DEFAULT_PROJECT_ID,
    skill: Optional[str] = None,
    module: Optional[str] = None,
    limit: int = 10,
    user: dict[str, Any] = Depends(auth.require_user),
) -> list[dict[str, Any]]:
    memberships.assert_project_access(user, project_id)
    return memory.list_precedent(
        project_id, skill=skill, module=module, limit=limit
    )


@router.post("/api/break-glass/open")
def open_break_glass(
    body: BreakGlassOpenRequest,
    user: dict[str, Any] = Depends(require_capability("break_glass")),
) -> dict[str, Any]:
    memberships.assert_project_access(user, body.project_id)
    try:
        return break_glass.open_session(
            body.project_id,
            opened_by=user.get("username") or user.get("name") or "operator",
            reason=body.reason,
            ttl_minutes=body.ttl_minutes,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/api/break-glass/status")
def break_glass_status(
    project_id: str = DEFAULT_PROJECT_ID,
    user: dict[str, Any] = Depends(auth.require_user),
) -> dict[str, Any]:
    memberships.assert_project_access(user, project_id)
    return break_glass.status(project_id)


@router.post("/api/break-glass/expire")
def expire_break_glass(
    project_id: str = DEFAULT_PROJECT_ID,
    session_id: Optional[str] = None,
    user: dict[str, Any] = Depends(require_capability("break_glass")),
) -> dict[str, Any]:
    memberships.assert_project_access(user, project_id)
    return break_glass.expire(project_id, session_id)


@router.post("/api/delivery/runs")
def create_delivery_run(
    body: DeliveryCreateRequest,
    user: dict[str, Any] = Depends(auth.require_user),
) -> dict[str, Any]:
    assert_capability(user, "propose_write")
    memberships.assert_project_access(user, body.project_id)
    if projects.get_project(body.project_id) is None:
        raise HTTPException(status_code=404, detail="Project not found")
    return delivery.create_run(
        body.project_id,
        created_by=user.get("username") or "",
    )


@router.get("/api/delivery/runs")
def list_delivery_runs(
    project_id: str = DEFAULT_PROJECT_ID,
    user: dict[str, Any] = Depends(auth.require_user),
) -> list[dict[str, Any]]:
    memberships.assert_project_access(user, project_id)
    return delivery.list_runs(project_id)


@router.get("/api/delivery/runs/{run_id}")
def get_delivery_run(
    run_id: str,
    _user: dict[str, Any] = Depends(auth.require_user),
) -> dict[str, Any]:
    row = delivery.get_run(run_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Delivery run not found")
    return row


@router.post("/api/delivery/runs/{run_id}/docs")
def delivery_ingest_docs(
    run_id: str,
    body: DeliveryDocsRequest,
    user: dict[str, Any] = Depends(auth.require_user),
) -> dict[str, Any]:
    try:
        return delivery.ingest_docs(
            run_id, docs=body.docs, user_role=user.get("role") or "viewer"
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc


@router.post("/api/delivery/runs/{run_id}/transition")
def delivery_transition(
    run_id: str,
    body: DeliveryTransitionRequest,
    user: dict[str, Any] = Depends(auth.require_user),
) -> dict[str, Any]:
    try:
        return delivery.transition(
            run_id,
            to_stage=body.to_stage,
            user_role=user.get("role") or "viewer",
            artifact_key=body.artifact_key,
            artifact_value=body.artifact_value,
            approved_by=user.get("username") or "",
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/api/modules/{module}/actuate")
def actuate_module(
    module: str,
    body: ActuatorRequest,
    user: dict[str, Any] = Depends(auth.require_user),
) -> dict[str, Any]:
    finding = dict(body.finding or {})
    finding.setdefault("project_id", body.project_id)
    memberships.assert_project_access(user, body.project_id)
    try:
        return module_actuators.actuate(
            module,
            user=user,
            finding=finding,
            mode=body.mode,
            tier=body.tier,
            environment=body.environment,
        )
    except HTTPException:
        raise
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


# --- Organizations, invites, membership requests ---


class OrgCreateRequest(BaseModel):
    name: str
    slug: str = ""
    org_admin_user_id: Optional[str] = None


class OrgAdminAssignRequest(BaseModel):
    user_id: str


class InviteCreateRequest(BaseModel):
    email: str
    invited_role: str = "developer"
    org_role: str = "member"
    project_id: Optional[str] = None
    project_role: str = "developer"


class InviteAcceptRequest(BaseModel):
    token: str
    password: str
    display_name: str = ""
    username: Optional[str] = None


class MemberRequestBody(BaseModel):
    action: Literal["add", "remove", "update_role"] = "add"
    target_email: str = ""
    target_user_id: str = ""
    project_role: str = "developer"
    reason: str = ""


class MemberDecideBody(BaseModel):
    decision: Literal["approved", "rejected"]
    token: Optional[str] = None


@router.get("/api/orgs")
def list_orgs(user: dict[str, Any] = Depends(auth.require_user)) -> list[dict[str, Any]]:
    return orgs.list_orgs_for_user(user)


@router.post("/api/orgs")
def create_org(
    body: OrgCreateRequest,
    user: dict[str, Any] = Depends(require_capability("create_org")),
) -> dict[str, Any]:
    try:
        return orgs.create_org(
            name=body.name,
            created_by=str(user.get("id") or ""),
            org_admin_user_id=body.org_admin_user_id,
            slug=body.slug or None,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/api/orgs/{org_id}")
def get_org(
    org_id: str,
    user: dict[str, Any] = Depends(auth.require_user),
) -> dict[str, Any]:
    memberships.assert_org_access(user, org_id)
    row = orgs.get_org(org_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Organization not found")
    return row


@router.post("/api/orgs/{org_id}/admins")
def assign_org_admin(
    org_id: str,
    body: OrgAdminAssignRequest,
    user: dict[str, Any] = Depends(require_capability("create_org")),
) -> dict[str, Any]:
    try:
        return orgs.assign_org_admin(org_id=org_id, user_id=body.user_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/api/orgs/{org_id}/members")
def list_org_members(
    org_id: str,
    user: dict[str, Any] = Depends(auth.require_user),
) -> list[dict[str, Any]]:
    memberships.assert_org_access(user, org_id)
    return memberships.list_org_members(org_id)


@router.get("/api/orgs/{org_id}/projects")
def list_org_projects(
    org_id: str,
    user: dict[str, Any] = Depends(auth.require_user),
) -> list[dict[str, Any]]:
    memberships.assert_org_access(user, org_id)
    return orgs.list_org_projects(org_id)


@router.post("/api/orgs/{org_id}/invites")
def create_org_invite(
    org_id: str,
    body: InviteCreateRequest,
    user: dict[str, Any] = Depends(auth.require_user),
) -> dict[str, Any]:
    memberships.assert_org_admin(user, org_id)
    try:
        return invites.create_invite(
            org_id=org_id,
            email=body.email,
            invited_by=str(user.get("id") or ""),
            invited_role=body.invited_role,
            org_role=body.org_role,
            project_id=body.project_id,
            project_role=body.project_role,
            inviter_name=str(user.get("name") or user.get("username") or ""),
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/api/orgs/{org_id}/invites")
def list_org_invites(
    org_id: str,
    user: dict[str, Any] = Depends(auth.require_user),
) -> list[dict[str, Any]]:
    memberships.assert_org_admin(user, org_id)
    return invites.list_invites(org_id)


@router.get("/api/invites/peek")
def peek_invite(token: str) -> dict[str, Any]:
    try:
        return invites.peek_invite(token)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/api/invites/accept")
def accept_invite(body: InviteAcceptRequest) -> dict[str, Any]:
    try:
        result = invites.accept_invite(
            token=body.token,
            password=body.password,
            display_name=body.display_name,
            username=body.username,
        )
        # Auto-login session
        session = auth.authenticate(result["username"], body.password)
        if session:
            result["session"] = session
        return result
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/api/projects/{project_id}/members")
def list_project_members(
    project_id: str,
    user: dict[str, Any] = Depends(auth.require_user),
) -> list[dict[str, Any]]:
    memberships.assert_project_access(user, project_id)
    return memberships.list_project_members(project_id)


@router.post("/api/projects/{project_id}/member-requests")
def create_member_request(
    project_id: str,
    body: MemberRequestBody,
    user: dict[str, Any] = Depends(auth.require_user),
) -> dict[str, Any]:
    memberships.assert_project_access(user, project_id)
    try:
        return membership_requests.create_request(
            project_id=project_id,
            requested_by=user,
            action=body.action,
            target_email=body.target_email,
            target_user_id=body.target_user_id,
            project_role=body.project_role,
            reason=body.reason,
        )
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/api/orgs/{org_id}/member-requests")
def list_member_requests(
    org_id: str,
    status: str = "pending",
    user: dict[str, Any] = Depends(auth.require_user),
) -> list[dict[str, Any]]:
    memberships.assert_org_admin(user, org_id)
    return membership_requests.list_requests(org_id=org_id, status=status)


@router.post("/api/member-requests/{request_id}/decide")
def decide_member_request(
    request_id: str,
    body: MemberDecideBody,
    user: dict[str, Any] = Depends(auth.require_user),
) -> dict[str, Any]:
    try:
        return membership_requests.decide_request(
            request_id=request_id,
            decision=body.decision,
            decided_by=user,
            token=body.token,
        )
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/api/member-requests/decide-email")
def decide_member_request_email(body: MemberDecideBody, request_id: str = "") -> dict[str, Any]:
    """Approve/reject via email token without full Org Admin session (token proves authority)."""
    rid = request_id
    if not rid:
        raise HTTPException(status_code=400, detail="request_id required")
    if not body.token:
        raise HTTPException(status_code=400, detail="token required")
    try:
        return membership_requests.decide_request(
            request_id=rid,
            decision=body.decision,
            decided_by={"id": "", "name": "email"},
            token=body.token,
        )
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/api/smtp/status")
def smtp_status(
    _user: dict[str, Any] = Depends(require_min_role("org_admin")),
) -> dict[str, Any]:
    return {
        "configured": mailer.smtp_configured(),
        "public_app_url": mailer.public_app_url(),
    }