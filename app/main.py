"""FastAPI application: chatbot, skill catalog, wiki and connection settings."""
import json
import hmac
import os
from contextlib import asynccontextmanager
from datetime import date
from pathlib import Path
from typing import Any, Literal, Optional

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[1] / ".env")

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from starlette.responses import JSONResponse

from app.core import (
    auth,
    azure_client,
    config,
)
from app.tenancy import (
    memberships,
    projects,
)
from app.chat import (
    chat_memory,
    chats,
    orchestrator,
)
from app.platform import connections
from app import __version__
from app.core.db import DEFAULT_PROJECT_ID, init_db
from app.execution import chat_actions
from app.execution import service as execution
from app.intelligence import scheduler as intel_scheduler
from app.intelligence import workflows as intel
from app.intelligence.queue import enqueue_run
from app.providers import github_infra
from app.skills import WORKFLOW_SAFE, registry

_FRONTEND_DIR = Path(__file__).resolve().parents[1] / "frontend" / "out"


@asynccontextmanager
async def lifespan(_: FastAPI):
    from app.core import (
        observability,
        prompts,
    )

    observability.ensure_host_alias()
    init_db()
    auth.ensure_seed_user()
    from app.core.db import ensure_tenancy_seed

    ensure_tenancy_seed()
    try:
        prompts.seed_core_prompts()
    except Exception:
        pass
    intel.seed_default_workflows(DEFAULT_PROJECT_ID)
    try:
        from app.agents.solution_architect.graph import setup_checkpointer

        setup_checkpointer()
    except Exception:
        pass
    intel_scheduler.start_scheduler()
    from app.org_executors.controller import start_controller, stop_controller

    start_controller()
    try:
        yield
    finally:
        stop_controller()
        intel_scheduler.shutdown_scheduler()
        observability.flush()


app = FastAPI(title="InfraLens Skills Suite", version=__version__, lifespan=lifespan)

_PUBLIC_API_PATHS = frozenset(
    {
        "/api/health",
        "/api/auth/login",
        "/api/invites/peek",
        "/api/invites/accept",
        "/api/member-requests/decide-email",
        "/api/providers/github/oauth/callback",
        "/api/providers/azure/oauth/callback",
    }
)

_WRITE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})
_VIEWER_WRITE_ALLOW = frozenset(
    {
        "/api/auth/login",
        "/api/auth/me",
    }
)


class JwtAuthMiddleware:
    """Require a Bearer JWT for /api routes without buffering SSE streams.

    Pure ASGI (not BaseHTTPMiddleware): Starlette's BaseHTTPMiddleware can stall
    other requests while a long-lived chat stream is still generating.
    """

    def __init__(self, app: Any) -> None:
        self.app = app

    async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        request = Request(scope, receive)
        if request.method == "OPTIONS":
            await self.app(scope, receive, send)
            return
        path = request.url.path.rstrip("/") or "/"
        if path.startswith("/api") and path not in _PUBLIC_API_PATHS:
            try:
                user = auth.verify_token(
                    auth.bearer_token(request.headers.get("Authorization"))
                )
            except Exception:
                user = None
            if user is None:
                response = JSONResponse({"detail": "Not authenticated"}, status_code=401)
                await response(scope, receive, send)
                return
            request.state.user = user
            if (
                request.method in _WRITE_METHODS
                and path not in _VIEWER_WRITE_ALLOW
                and not path.endswith("/oauth/callback")
            ):
                from app.core.rbac import has_min_role

                if not has_min_role(user.get("role"), "developer"):
                    response = JSONResponse(
                        {"detail": "Viewer role is read-only"},
                        status_code=403,
                    )
                    await response(scope, receive, send)
                    return
        await self.app(scope, receive, send)


# Last-added middleware is outermost. CORS must wrap JWT auth so browser
# clients on :3000 still receive Access-Control-* headers on 401/403 short-circuits.
app.add_middleware(JwtAuthMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

from app.api.routes_mvp import router as mvp_router
from app.api.routes_engineering import router as engineering_router

app.include_router(mvp_router)
app.include_router(engineering_router)


def _refresh_chat_memory(chat_id: str) -> None:
    """Memory is best-effort; a failed refresh must not fail the chat turn."""
    try:
        chat_memory.refresh_memory(chat_id)
    except Exception:
        return


def _persist_chat_iac(
    project_id: str,
    skills: list[Any] | None,
    *,
    actor: str = "",
    forced: str = "",
) -> dict[str, Any]:
    names = {str(item) for item in (skills or []) if item}
    if forced:
        names.add(forced)
    if "terraform_generator" not in names or not project_id:
        return {}
    try:
        from app.platform.engineering.iac_generate import generate_missing_for_project

        return generate_missing_for_project(project_id, actor=actor)
    except Exception:
        return {}


def _with_iac_note(reply: str, persisted: dict[str, Any]) -> str:
    count = int(persisted.get("count") or 0)
    if count <= 0:
        return reply
    return (
        (reply or "")
        + f"\n\nAttached {count} delivery checklist artifacts from the architecture model. Nothing has been applied."
    )


def _sse_payload(event: dict[str, Any]) -> dict[str, Any]:
    """Keep SSE lines small so the client can parse `final` reliably."""
    return {key: value for key, value in event.items() if key not in {"architecture", "mermaid"}}


class ChatRequest(BaseModel):
    message: str
    chat_id: Optional[str] = None
    edit_message_id: Optional[str] = None
    project_id: str = DEFAULT_PROJECT_ID
    mode: Literal["agent", "plan"] = "agent"
    skill: Optional[str] = None
    action_scope: Literal["read_only", "write"] = "read_only"
    access_level: Literal["ask_approval", "auto_approve", "full_access"] = "ask_approval"


class PlanStepRequest(BaseModel):
    skill: str
    objective: str = ""


class ActionRequest(BaseModel):
    project_id: str = DEFAULT_PROJECT_ID
    provider: Literal["azure", "aws", "github"]
    executable: Literal["az", "aws", "gh"]
    args: list[str] = []
    target: str = ""
    access_scope: Literal["read_only", "write"] = "read_only"
    access_level: Literal["ask_approval", "auto_approve", "full_access"] = "ask_approval"
    expected_result: str = ""
    risk: str = ""
    rollback: str = ""
    why: str = ""
    blast_radius: str = ""
    degrade_plan: str = ""
    preflight: list[str] = []
    preflight_expect: str = ""
    verify: list[str] = []
    steps: list[dict[str, Any]] = []
    requested_by: str = "user"


class ExecutePlanRequest(BaseModel):
    chat_id: str
    project_id: str = DEFAULT_PROJECT_ID
    steps: list[PlanStepRequest] = []
    action_scope: Literal["read_only", "write"] = "read_only"
    access_level: Literal["ask_approval", "auto_approve", "full_access"] = "ask_approval"
    actions: list[ActionRequest] = []


class ActionDecisionRequest(BaseModel):
    approver: str = "user"
    reason: str = ""


class LoginRequest(BaseModel):
    username: str
    password: str


class ExecutorEventRequest(BaseModel):
    type: str
    payload: dict[str, Any] = {}


class ExecutorResultRequest(BaseModel):
    status: Literal["succeeded", "failed", "verification_failed", "rolled_back", "canceled"]
    result: dict[str, Any] = {}
    error: str = ""


class RenameRequest(BaseModel):
    title: str


class ProjectRequest(BaseModel):
    name: str


class ReposRequest(BaseModel):
    repos: list[str] = []


def _require_project(
    project_id: str,
    user: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    project = projects.get_project(project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    if user is not None:
        from app.tenancy import memberships

        memberships.assert_project_access(user, project_id)
    return project


class SkillInfo(BaseModel):
    name: str
    category: str
    description: str
    triggers: list[str]
    is_agentic: bool = False
    auto_routable: bool = True


class SkillDetail(SkillInfo):
    wiki: str
    parameters: dict[str, Any]


class ConnectionRequest(BaseModel):
    method: str
    fields: dict[str, Any] = {}


class AzureConfigRequest(BaseModel):
    endpoint: str = ""
    api_key: str = ""
    deployment: str = "gpt-4o"
    api_version: str = "2024-10-21"


@app.get("/api/health")
def health() -> dict[str, Any]:
    """Report service status and whether Azure OpenAI is configured."""
    azure = config.get_azure_config()
    return {
        "status": "ok",
        "version": __version__,
        "azure_configured": azure.configured,
        "deployment": azure.deployment,
        "skill_count": len(registry.all()),
        "write_actions_enabled": True,
        "write_actions_controlled_by_ui": True,
    }


@app.get("/api/config/azure-openai")
def get_azure_config_route(
    user: dict[str, Any] = Depends(auth.require_user),
) -> dict[str, Any]:
    """Platform LLM config — separate from project Azure cloud account."""
    azure = config.get_azure_config()
    return {
        "endpoint": azure.endpoint if memberships.is_super_admin(user) or azure.configured else "",
        "deployment": azure.deployment,
        "api_version": azure.api_version,
        "configured": azure.configured,
        "has_key": bool(azure.api_key),
        "scope": "platform",
        "editable": memberships.is_super_admin(user),
        "note": (
            "Platform LLM for chat/skills (Super Admin). Separate from project Azure account "
            "used for cloud workflows."
        ),
    }


@app.put("/api/config/azure-openai")
def put_azure_config_route(
    body: AzureConfigRequest,
    user: dict[str, Any] = Depends(auth.require_user),
) -> dict[str, Any]:
    """Save Azure OpenAI config — Super Admin only."""
    if not memberships.is_super_admin(user):
        raise HTTPException(status_code=403, detail="Super Admin required to edit platform LLM")
    config.set_azure_config(
        endpoint=body.endpoint,
        api_key=body.api_key,
        deployment=body.deployment,
        api_version=body.api_version,
    )
    return get_azure_config_route(user)


@app.post("/api/auth/login")
def login(body: LoginRequest) -> dict[str, Any]:
    """Authenticate against the users table and return a JWT."""
    session = auth.authenticate(body.username, body.password)
    if session is None:
        raise HTTPException(status_code=401, detail="Invalid username or password")
    return session


@app.get("/api/auth/me")
def auth_me(user: dict[str, Any] = Depends(auth.require_user)) -> dict[str, Any]:
    """Return the current user for a valid Bearer JWT."""
    from app.tenancy import memberships

    return {"user": memberships.enrich_user_public(user)}


def _skill_sort_key(skill: Any) -> str:
    return skill.name.replace("_", " ").lower()


@app.get("/api/skills", response_model=list[SkillInfo])
def list_skills() -> list[SkillInfo]:
    """Return the catalog of available skills for the UI, sorted A–Z."""
    return [
        SkillInfo(
            name=s.name,
            category=s.category,
            description=s.description,
            triggers=s.triggers,
            is_agentic=bool(getattr(s, "is_agentic", False)),
            auto_routable=bool(getattr(s, "auto_routable", True)),
        )
        for s in sorted(registry.all(), key=_skill_sort_key)
    ]


@app.get("/api/skills/{name}", response_model=SkillDetail)
def get_skill(name: str) -> SkillDetail:
    """Return full detail (including wiki docs) for one skill."""
    skill = registry.get(name)
    if skill is None:
        raise HTTPException(status_code=404, detail=f"Unknown skill: {name}")
    return SkillDetail(
        name=skill.name,
        category=skill.category,
        description=skill.description,
        triggers=skill.triggers,
        wiki=skill.wiki,
        parameters=skill.parameters,
        is_agentic=bool(getattr(skill, "is_agentic", False)),
        auto_routable=bool(getattr(skill, "auto_routable", True)),
    )


@app.get("/api/projects")
def list_projects(user: dict[str, Any] = Depends(auth.require_user)) -> list[dict[str, Any]]:
    """List projects the current user can access."""
    return projects.list_projects(user=user)


@app.post("/api/projects")
def create_project(
    body: ProjectRequest,
    user: dict[str, Any] = Depends(auth.require_user),
) -> dict[str, Any]:
    """Create a new project in the user's org, seeded with starter workflows."""
    from app.tenancy import memberships
    from app.core.rbac import assert_capability, normalize_role

    assert_capability(user, "create_project")
    try:
        org_id = memberships.ensure_user_org(user)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    role = normalize_role(user.get("role"))
    project_role = (
        "devops_lead"
        if role in {"super_admin", "org_admin", "devops_lead"}
        else ("devops_engineer" if role == "devops_engineer" else "developer")
    )
    project = projects.create_project(
        body.name,
        org_id=org_id,
        owner_user_id=str(user.get("id") or "") or None,
        owner_project_role=project_role,
        reuse_empty=True,
    )
    intel.seed_default_workflows(project["id"])
    intel_scheduler.sync_schedules()
    return project


@app.patch("/api/projects/{project_id}")
def rename_project(
    project_id: str,
    body: ProjectRequest,
    user: dict[str, Any] = Depends(auth.require_user),
) -> dict[str, Any]:
    """Rename a project."""
    from app.tenancy import memberships

    memberships.assert_project_access(user, project_id)
    project = projects.rename_project(project_id, body.name)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    return project


@app.put("/api/projects/{project_id}/default")
def set_default_project(
    project_id: str,
    user: dict[str, Any] = Depends(auth.require_user),
) -> dict[str, Any]:
    """Set the sole persisted default project used on a fresh page load."""
    from app.tenancy import memberships

    memberships.assert_project_access(user, project_id)
    project = projects.set_default(project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    return project


@app.delete("/api/projects/{project_id}")
def delete_project(
    project_id: str,
    user: dict[str, Any] = Depends(auth.require_user),
) -> dict[str, bool]:
    """Delete a project and everything scoped to it (the default cannot be deleted)."""
    from app.tenancy import memberships
    from app.core.rbac import assert_capability

    assert_capability(user, "delete_project")
    memberships.assert_project_access(user, project_id)
    org_id = memberships.project_org_id(project_id)
    if org_id:
        memberships.assert_org_admin(user, org_id)
    project = projects.get_project(project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    if project.get("is_default"):
        raise HTTPException(
            status_code=400,
            detail="Cannot delete the default project. Make another project the default first, then delete this one.",
        )
    deleted = projects.delete_project(project_id)
    if not deleted:
        raise HTTPException(
            status_code=400,
            detail="Could not delete this project. Make another project the default first.",
        )
    intel_scheduler.sync_schedules()
    return {"deleted": True}


@app.get("/api/projects/{project_id}/repos")
def get_project_repos(
    project_id: str,
    user: dict[str, Any] = Depends(auth.require_user),
) -> dict[str, Any]:
    """Return the repos mapped to a project plus every repo available to map."""
    _require_project(project_id, user)
    available: list[str] = []
    error: Optional[str] = None
    if github_infra.is_connected(project_id):
        try:
            available = github_infra.list_repo_names(project_id)
        except github_infra.GitHubApiError as exc:
            error = str(exc)
    return {
        "mapped": projects.get_repos(project_id),
        "available": available,
        "github_connected": github_infra.is_connected(project_id),
        "error": error,
    }


@app.put("/api/projects/{project_id}/repos")
def set_project_repos(
    project_id: str,
    body: ReposRequest,
    user: dict[str, Any] = Depends(auth.require_user),
) -> dict[str, Any]:
    """Set which repositories a project is allowed to inspect."""
    _require_project(project_id, user)
    project = projects.set_repos(project_id, body.repos)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    return project


@app.get("/api/projects/{project_id}/connections")
def get_connections(
    project_id: str,
    user: dict[str, Any] = Depends(auth.require_user),
) -> list[dict[str, Any]]:
    """Return public (secret-free) status of a project's provider connections."""
    _require_project(project_id, user)
    return connections.all_status(project_id)


@app.get("/api/projects/{project_id}/provider-status")
def get_provider_status(
    project_id: str,
    action_scope: Literal["read_only", "write"] = "read_only",
    user: dict[str, Any] = Depends(auth.require_user),
) -> list[dict[str, Any]]:
    """Return the selected project's provider readiness without secrets."""
    _require_project(project_id, user)
    return chat_actions.provider_status(project_id, action_scope)


@app.put("/api/projects/{project_id}/connections/{provider}")
def put_connection(
    project_id: str,
    provider: str,
    body: ConnectionRequest,
    user: dict[str, Any] = Depends(auth.require_user),
) -> dict[str, Any]:
    """Save or update a provider connection within a project."""
    from app.core.rbac import assert_capability

    assert_capability(user, "connect_provider")
    _require_project(project_id, user)
    if provider not in connections.PROVIDERS:
        raise HTTPException(status_code=404, detail=f"Unknown provider: {provider}")
    result = connections.set_connection(project_id, provider, body.method, body.fields)
    if provider in {"azure", "aws"}:
        enabled = intel.enable_workflows_when_ready(project_id)
        if enabled:
            intel_scheduler.sync_schedules()
    return result


@app.delete("/api/projects/{project_id}/connections/{provider}")
def delete_connection(
    project_id: str,
    provider: str,
    user: dict[str, Any] = Depends(auth.require_user),
) -> dict[str, Any]:
    """Disconnect a provider within a project."""
    _require_project(project_id, user)
    if provider not in connections.PROVIDERS:
        raise HTTPException(status_code=404, detail=f"Unknown provider: {provider}")
    return connections.remove_connection(project_id, provider)


def _action_values(body: ActionRequest) -> dict[str, Any]:
    return {
        "project_id": body.project_id,
        "provider": body.provider,
        "executable": body.executable,
        "args": body.args,
        "target": body.target,
        "access_scope": body.access_scope,
        "access_level": body.access_level,
        "expected_result": body.expected_result,
        "risk": body.risk,
        "rollback": body.rollback,
        "why": body.why,
        "blast_radius": body.blast_radius,
        "degrade_plan": body.degrade_plan,
        "preflight": body.preflight,
        "preflight_expect": body.preflight_expect,
        "verify": body.verify,
        "steps": body.steps,
        "requested_by": body.requested_by,
    }


@app.post("/api/actions/preview")
def preview_action(body: ActionRequest) -> dict[str, Any]:
    """Validate a structured provider operation without dispatching it."""
    _require_project(body.project_id)
    if body.provider == "github" and "/" in body.target:
        mapped = {repo.lower() for repo in projects.get_repos(body.project_id)}
        if body.target.lower() not in mapped:
            raise HTTPException(status_code=400, detail="GitHub action target is outside the repositories mapped to this project")
    try:
        from app.execution.validation import command_preview, operation_hash, validate_operation

        operation = validate_operation(
            body.provider, body.executable, body.args, body.target, body.access_scope,
            body.preflight, body.verify,
        )
        operation.update({"expected_result": body.expected_result[:1000], "risk": body.risk[:1000], "rollback": body.rollback[:1000]})
        return {
            "provider": body.provider,
            "target": body.target,
            "access_scope": body.access_scope,
            "operation": operation,
            "command_preview": command_preview(operation),
            "operation_hash": operation_hash(operation, body.access_scope),
            "approval_required": body.access_scope == "write",
            "write_enabled": True,
            "write_control": "ui",
        }
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/actions")
def create_action(
    body: ActionRequest,
    user: dict[str, Any] = Depends(auth.require_user),
) -> dict[str, Any]:
    """Persist and dispatch a safe read action, or create a write approval."""
    from app.core.rbac import assert_capability

    if body.access_scope == "write":
        assert_capability(user, "propose_write")
    _require_project(body.project_id)
    try:
        return execution.create_action(**_action_values(body))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/actions/{action_id}")
def get_action(action_id: str) -> dict[str, Any]:
    try:
        return execution.get_action(action_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get("/api/actions/{action_id}/events")
def get_action_events(action_id: str) -> list[dict[str, Any]]:
    try:
        return execution.list_events(action_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get("/api/actions/{action_id}/diagnostics")
def diagnose_action(action_id: str) -> dict[str, Any]:
    try:
        return execution.diagnose_action(action_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.post("/api/actions/{action_id}/approve")
def approve_action(
    action_id: str,
    body: ActionDecisionRequest,
    user: dict[str, Any] = Depends(auth.require_user),
) -> dict[str, Any]:
    from app.core.rbac import assert_capability

    assert_capability(user, "approve_human")
    try:
        return execution.approve_action(
            action_id, body.approver or user.get("username") or "user"
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/actions/{action_id}/reject")
def reject_action(action_id: str, body: ActionDecisionRequest) -> dict[str, Any]:
    try:
        return execution.reject_action(action_id, body.approver, body.reason)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/actions/{action_id}/cancel")
def cancel_action(action_id: str, body: ActionDecisionRequest) -> dict[str, Any]:
    try:
        return execution.cancel_action(action_id, body.approver)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


def _require_executor(
    key: Optional[str], provider: Optional[str], org_id: Optional[str] = None
) -> tuple[str, str]:
    expected = os.environ.get("EXECUTOR_SERVICE_KEY", "dev-executor-key")
    if not key or not hmac.compare_digest(key, expected):
        raise HTTPException(status_code=403, detail="Invalid executor credentials")
    if provider not in {"azure", "aws", "github"}:
        raise HTTPException(status_code=403, detail="Invalid executor provider")
    clean_org = (org_id or "").strip()
    if not clean_org:
        raise HTTPException(status_code=403, detail="Missing executor org id")
    return provider, clean_org


@app.get("/internal/execution/jobs/{action_id}/claim")
def claim_action_for_executor(
    action_id: str,
    provider: str,
    x_executor_key: Optional[str] = Header(default=None),
    x_executor_provider: Optional[str] = Header(default=None),
    x_executor_org_id: Optional[str] = Header(default=None),
) -> dict[str, Any]:
    """Private control-plane endpoint; credentials are never returned publicly."""
    exec_provider, exec_org = _require_executor(
        x_executor_key, x_executor_provider, x_executor_org_id
    )
    if exec_provider != provider:
        raise HTTPException(status_code=403, detail="Executor provider mismatch")
    try:
        return execution.claim_for_executor(
            action_id, provider, executor_org_id=exec_org
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.post("/internal/execution/jobs/{action_id}/events")
def record_executor_event(
    action_id: str,
    body: ExecutorEventRequest,
    x_executor_key: Optional[str] = Header(default=None),
    x_executor_provider: Optional[str] = Header(default=None),
    x_executor_org_id: Optional[str] = Header(default=None),
) -> dict[str, bool]:
    provider, exec_org = _require_executor(
        x_executor_key, x_executor_provider, x_executor_org_id
    )
    if body.type not in {"action_output", "action_verified"}:
        raise HTTPException(status_code=400, detail="Unsupported executor event")
    try:
        execution.validate_executor_provider(action_id, provider)
        execution.validate_executor_org(action_id, exec_org)
        execution.append_event(action_id, body.type, body.payload)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    return {"recorded": True}


@app.get("/internal/execution/jobs/{action_id}/canceled")
def check_executor_cancellation(
    action_id: str,
    provider: str,
    x_executor_key: Optional[str] = Header(default=None),
    x_executor_provider: Optional[str] = Header(default=None),
    x_executor_org_id: Optional[str] = Header(default=None),
) -> dict[str, bool]:
    exec_provider, exec_org = _require_executor(
        x_executor_key, x_executor_provider, x_executor_org_id
    )
    if exec_provider != provider:
        raise HTTPException(status_code=403, detail="Executor provider mismatch")
    try:
        execution.validate_executor_org(action_id, exec_org)
        return {"canceled": execution.is_canceled(action_id, provider)}
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc


@app.post("/internal/execution/jobs/{action_id}/result")
def record_executor_result(
    action_id: str,
    body: ExecutorResultRequest,
    x_executor_key: Optional[str] = Header(default=None),
    x_executor_provider: Optional[str] = Header(default=None),
    x_executor_org_id: Optional[str] = Header(default=None),
) -> dict[str, bool]:
    provider, exec_org = _require_executor(
        x_executor_key, x_executor_provider, x_executor_org_id
    )
    try:
        execution.validate_executor_provider(action_id, provider)
        execution.validate_executor_org(action_id, exec_org)
        execution.mark_result(action_id, body.status, body.result, body.error)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    return {"recorded": True}


@app.get("/api/chats")
def list_chats(project_id: Optional[str] = None) -> list[dict[str, Any]]:
    """List saved chats for a project (most recently updated first)."""
    return chats.list_chats(project_id)


@app.post("/api/chats")
def create_chat(project_id: str = DEFAULT_PROJECT_ID) -> dict[str, Any]:
    """Create a new empty chat in a project."""
    return chats.create_chat(project_id=project_id)


@app.get("/api/chats/{chat_id}")
def get_chat(chat_id: str) -> dict[str, Any]:
    """Return a chat with its full message history."""
    chat = chats.get_chat(chat_id)
    if chat is None:
        raise HTTPException(status_code=404, detail="Chat not found")
    return chat


@app.patch("/api/chats/{chat_id}")
def rename_chat(chat_id: str, body: RenameRequest) -> dict[str, Any]:
    """Rename a chat."""
    chat = chats.rename_chat(chat_id, body.title)
    if chat is None:
        raise HTTPException(status_code=404, detail="Chat not found")
    return chat


@app.delete("/api/chats/{chat_id}")
def delete_chat(chat_id: str) -> dict[str, bool]:
    """Delete a chat and its messages."""
    return {"deleted": chats.delete_chat(chat_id)}


def _request_user_id(http_request: Request) -> Optional[str]:
    user = getattr(http_request.state, "user", None) or {}
    if isinstance(user, dict):
        return user.get("username") or user.get("id")
    return None


@app.post("/api/chat/stream")
def chat_stream(request: ChatRequest, http_request: Request) -> StreamingResponse:
    """Stream an orchestrated chat turn as Server-Sent Events."""
    from app.core import observability

    if request.skill and registry.get(request.skill) is None:
        raise HTTPException(status_code=400, detail=f"Unknown skill: {request.skill}")
    if request.skill == "solution_architect":
        from app.core.rbac import assert_capability

        assert_capability(getattr(http_request.state, "user", None) or {}, "run_architecture")

    chat_id = request.chat_id
    user_id = _request_user_id(http_request)
    if not chat_id or chats.get_chat(chat_id) is None:
        chat_id = chats.create_chat(request.message, project_id=request.project_id)["id"]
    if request.edit_message_id:
        if not chats.replace_user_message(chat_id, request.edit_message_id, request.message):
            raise HTTPException(status_code=404, detail="User message not found")
    else:
        chats.add_message(chat_id, "user", request.message)

    def sse(event: dict[str, Any]) -> str:
        return f"data: {json.dumps(_sse_payload(event), default=str)}\n\n"

    def generate() -> Any:
        # Do not wrap yields in tracing_context — ASGI may resume this generator
        # in a different Context, which makes ContextVar.reset fail.
        tokens = observability.bind_tracing(
            session_id=chat_id,
            user_id=user_id,
            tags=["chat", request.mode, f"project:{request.project_id}"],
            feature="chat",
            generation_name="chat-stream",
        )
        saved_assistant = False
        try:
            yield sse({"type": "chat", "chat_id": chat_id})
            yield sse({"type": "status", "text": "Working on it"})

            special_action: Optional[dict[str, Any]] = None
            if request.mode == "agent" and request.skill != "solution_architect":
                yield sse({"type": "status", "text": "Checking for a live action"})
                try:
                    special_action = chat_actions.handle_turn(
                        chat_id, request.project_id, request.message, request.action_scope, request.access_level
                    )
                except ValueError as exc:
                    special_action = {
                        "reply": f"I could not prepare that Azure action: {exc}",
                        "action": None,
                        "event_type": "action_failed",
                    }

            if special_action is not None:
                action = special_action.get("action")
                if action:
                    yield sse({
                        "type": "action_planned",
                        "action_id": action["id"],
                        "action": action,
                    })
                    yield sse({
                        "type": special_action.get("event_type", "approval_required"),
                        "action_id": action["id"],
                        "action": action,
                    })
                reply = str(special_action.get("reply", ""))
                yield sse({"type": "delta", "text": reply})
                meta = {"mode": "agent"}
                if action:
                    meta.update({"action_id": action["id"], "action_status": action.get("status")})
                if special_action.get("pending_resource_group_name"):
                    meta["pending_resource_group_name"] = special_action["pending_resource_group_name"]
                if special_action.get("pending_action_spec"):
                    meta["pending_action_spec"] = special_action["pending_action_spec"]
                chats.add_message(chat_id, "assistant", reply, meta)
                saved_assistant = True
                yield sse({
                    "type": "final",
                    "mode": "agent",
                    "reply": reply,
                    "chat_id": chat_id,
                    **({"required_action_scope": special_action["required_action_scope"]} if special_action.get("required_action_scope") else {}),
                    **({"action_id": action["id"], "action": action} if action else {}),
                })
                _refresh_chat_memory(chat_id)
                return

            if not config.get_azure_config().configured:
                reply = (
                    "Azure OpenAI is not configured yet. Open Settings and add your "
                    "Azure OpenAI endpoint and key. Chats, skills and wiki work "
                    "offline so you can still preview the suite.\n\n"
                    + chat_actions.provider_status_text(request.project_id, request.action_scope)
                )
                yield sse({"type": "delta", "text": reply})
                chats.add_message(chat_id, "assistant", reply, {"mode": request.mode})
                saved_assistant = True
                yield sse({"type": "final", "mode": request.mode, "reply": reply, "chat_id": chat_id})
                _refresh_chat_memory(chat_id)
                return

            history = chat_memory.get_model_context(
                chat_id, request.message, project_id=request.project_id
            )
            diagnostic_context = chat_actions.action_diagnostic_context(chat_id, request.message)
            if diagnostic_context:
                history.insert(0, {"role": "system", "content": diagnostic_context})
            final: dict[str, Any] = {}
            try:
                for event in orchestrator.run_chat_stream(
                    history,
                    request.project_id,
                    mode=request.mode,
                    skill=request.skill,
                    action_scope=request.action_scope,
                    access_level=request.access_level,
                    chat_id=chat_id,
                ):
                    if event.get("type") == "final":
                        final = event
                        continue
                    yield sse(event)
            except azure_client.AzureOpenAINotConfiguredError as exc:
                yield sse({"type": "delta", "text": str(exc)})
                final = {"mode": request.mode, "reply": str(exc)}
            except Exception as exc:  # noqa: BLE001 - surface a clean error to the client
                message = f"The request failed while generating a response: {exc}"
                yield sse({"type": "delta", "text": message})
                final = {"mode": request.mode, "reply": message}

            reply = str(final.get("reply") or "") or "I could not generate a reply."
            persisted = _persist_chat_iac(
                request.project_id,
                list(final.get("skills_used") or []),
                actor=user_id,
                forced=request.skill or "",
            )
            reply = _with_iac_note(reply, persisted)
            final["reply"] = reply
            if persisted:
                final["generated_artifacts"] = persisted.get("count") or 0
            chats.add_message(
                chat_id,
                "assistant",
                reply,
                {
                    "mode": final.get("mode"),
                    "skills_used": final.get("skills_used", []),
                    "charts": final.get("charts", []),
                },
            )
            saved_assistant = True
            final["chat_id"] = chat_id
            yield sse({"type": "final", **final})
            _refresh_chat_memory(chat_id)
        except Exception as exc:  # noqa: BLE001
            if saved_assistant:
                raise
            message = f"The request failed while generating a response: {exc}"
            try:
                chats.add_message(chat_id, "assistant", message, {"mode": request.mode, "error": True})
            except Exception:
                pass
            yield sse({"type": "delta", "text": message})
            yield sse({"type": "final", "mode": request.mode, "reply": message, "chat_id": chat_id})
        finally:
            try:
                observability.flush()
            except Exception:
                pass
            observability.reset_tracing(tokens)

    return StreamingResponse(generate(), media_type="text/event-stream")


@app.post("/api/chat/execute-plan")
def execute_plan(request: ExecutePlanRequest, http_request: Request) -> StreamingResponse:
    """Execute a plan the user approved (from plan mode), streaming the run."""
    from app.core import observability

    chat = chats.get_chat(request.chat_id)
    if chat is None:
        raise HTTPException(status_code=404, detail="Chat not found")

    steps = [
        orchestrator.PlanStep(skill=s.skill, objective=s.objective)
        for s in request.steps
        if registry.get(s.skill) is not None
    ]
    if any(step.skill == "solution_architect" for step in steps):
        from app.core.rbac import assert_capability

        assert_capability(getattr(http_request.state, "user", None) or {}, "run_architecture")
    action_jobs: list[dict[str, Any]] = []
    for action in request.actions:
        if action.project_id != request.project_id:
            raise HTTPException(status_code=400, detail="Action project does not match the plan project")
        if request.action_scope != action.access_scope:
            raise HTTPException(status_code=400, detail="Action scope does not match the plan scope")
        try:
            action_jobs.append(execution.create_action(**_action_values(action)))
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not steps and not action_jobs:
        raise HTTPException(status_code=400, detail="No runnable steps in the plan")

    chat_id = request.chat_id
    user_id = _request_user_id(http_request)

    def sse(event: dict[str, Any]) -> str:
        return f"data: {json.dumps(_sse_payload(event), default=str)}\n\n"

    def generate() -> Any:
        tokens = observability.bind_tracing(
            session_id=chat_id,
            user_id=user_id,
            tags=["chat", "plan-execute", f"project:{request.project_id}"],
            feature="chat",
            generation_name="execute-plan",
        )
        try:
            yield sse({"type": "chat", "chat_id": chat_id})
            for action in action_jobs:
                yield sse({"type": "action_planned", "action_id": action["id"], "action": action})
                if action["status"] == "awaiting_approval":
                    yield sse({"type": "approval_required", "action_id": action["id"], "action": action})
                else:
                    yield sse({"type": "action_queued", "action_id": action["id"], "action": action})

            if not config.get_azure_config().configured:
                reply = "Azure OpenAI is not configured yet. Open Settings to run plans."
                yield sse({"type": "delta", "text": reply})
                chats.add_message(chat_id, "assistant", reply, {"mode": "agent"})
                _refresh_chat_memory(chat_id)
                yield sse({"type": "final", "mode": "agent", "reply": reply, "chat_id": chat_id})
                return

            history = chat_memory.get_model_context(
                chat_id, project_id=request.project_id
            )
            diagnostic_context = chat_actions.action_diagnostic_context(chat_id)
            if diagnostic_context:
                history.insert(0, {"role": "system", "content": diagnostic_context})
            final: dict[str, Any] = {}
            try:
                for event in orchestrator.execute_plan_stream(
                    history,
                    request.project_id,
                    steps,
                    action_scope=request.action_scope,
                    access_level=request.access_level,
                    chat_id=chat_id,
                ):
                    if event.get("type") == "final":
                        final = event
                        continue
                    yield sse(event)
            except azure_client.AzureOpenAINotConfiguredError as exc:
                yield sse({"type": "delta", "text": str(exc)})
                final = {"mode": "agent", "reply": str(exc)}
            except Exception as exc:  # noqa: BLE001 - surface a clean error to the client
                message = f"The plan failed while executing: {exc}"
                yield sse({"type": "delta", "text": message})
                final = {"mode": "agent", "reply": message}

            reply = final.get("reply", "")
            persisted = _persist_chat_iac(
                request.project_id,
                list(final.get("skills_used") or [step.skill for step in steps]),
                actor=user_id,
            )
            reply = _with_iac_note(reply, persisted)
            final["reply"] = reply
            chats.add_message(
                chat_id,
                "assistant",
                reply,
                {
                    "mode": final.get("mode", "agent"),
                    "skills_used": final.get("skills_used", []),
                    "charts": final.get("charts", []),
                },
            )
            final["chat_id"] = chat_id
            yield sse({"type": "final", **final})
            _refresh_chat_memory(chat_id)
        finally:
            observability.flush()
            observability.reset_tracing(tokens)

    return StreamingResponse(generate(), media_type="text/event-stream")


@app.post("/api/chat")
def chat(request: ChatRequest, http_request: Request) -> dict[str, Any]:
    """Run one orchestrated chat turn, persisting both messages to the chat."""
    from app.core import observability

    if request.skill and registry.get(request.skill) is None:
        raise HTTPException(status_code=400, detail=f"Unknown skill: {request.skill}")
    if request.skill == "solution_architect":
        from app.core.rbac import assert_capability

        assert_capability(getattr(http_request.state, "user", None) or {}, "run_architecture")

    chat_id = request.chat_id
    user_id = _request_user_id(http_request)
    if not chat_id or chats.get_chat(chat_id) is None:
        chat_id = chats.create_chat(request.message, project_id=request.project_id)["id"]

    if request.edit_message_id:
        if not chats.replace_user_message(chat_id, request.edit_message_id, request.message):
            raise HTTPException(status_code=404, detail="User message not found")
    else:
        chats.add_message(chat_id, "user", request.message)

    with observability.tracing_context(
        session_id=chat_id,
        user_id=user_id,
        tags=["chat", request.mode, f"project:{request.project_id}"],
        feature="chat",
        generation_name="chat",
    ):
        try:
            if request.mode == "agent" and request.skill != "solution_architect":
                try:
                    special_action = chat_actions.handle_turn(
                        chat_id,
                        request.project_id,
                        request.message,
                        request.action_scope,
                        request.access_level,
                    )
                except ValueError as exc:
                    special_action = {
                        "reply": f"I could not prepare that Azure action: {exc}",
                        "action": None,
                    }
                if special_action is not None:
                    reply = str(special_action.get("reply", ""))
                    action = special_action.get("action")
                    meta = {"mode": "agent"}
                    if action:
                        meta.update(
                            {
                                "action_id": action["id"],
                                "action_status": action.get("status"),
                            }
                        )
                    if special_action.get("pending_resource_group_name"):
                        meta["pending_resource_group_name"] = special_action[
                            "pending_resource_group_name"
                        ]
                    if special_action.get("pending_action_spec"):
                        meta["pending_action_spec"] = special_action["pending_action_spec"]
                    chats.add_message(chat_id, "assistant", reply, meta)
                    _refresh_chat_memory(chat_id)
                    result = {"mode": "agent", "reply": reply, "chat_id": chat_id}
                    if special_action.get("required_action_scope"):
                        result["required_action_scope"] = special_action[
                            "required_action_scope"
                        ]
                    if action:
                        result.update({"action_id": action["id"], "action": action})
                    return result

            if not config.get_azure_config().configured:
                reply = (
                    "Azure OpenAI is not configured yet. Open Settings and add your "
                    "Azure OpenAI endpoint and key. Chats, skills and wiki work offline "
                    "so you can still preview the suite.\n\n"
                    + chat_actions.provider_status_text(
                        request.project_id, request.action_scope
                    )
                )
                turn = orchestrator.ChatTurn(mode=request.mode, reply=reply)
                chats.add_message(chat_id, "assistant", reply, {"mode": request.mode})
                _refresh_chat_memory(chat_id)
                result = turn.to_dict()
                result["chat_id"] = chat_id
                return result

            history = chat_memory.get_model_context(
                chat_id, request.message, project_id=request.project_id
            )
            diagnostic_context = chat_actions.action_diagnostic_context(
                chat_id, request.message
            )
            if diagnostic_context:
                history.insert(0, {"role": "system", "content": diagnostic_context})
            try:
                turn = orchestrator.run_chat(
                    history,
                    request.project_id,
                    mode=request.mode,
                    skill=request.skill,
                    action_scope=request.action_scope,
                    access_level=request.access_level,
                    chat_id=chat_id,
                )
            except azure_client.AzureOpenAINotConfiguredError as exc:
                turn = orchestrator.ChatTurn(mode=request.mode, reply=str(exc))

            persisted = _persist_chat_iac(
                request.project_id,
                list(turn.skills_used or []),
                actor=user_id,
                forced=request.skill or "",
            )
            turn.reply = _with_iac_note(turn.reply, persisted)
            chats.add_message(
                chat_id,
                "assistant",
                turn.reply,
                {
                    "mode": turn.mode,
                    "skills_used": turn.skills_used,
                    "charts": turn.charts,
                },
            )
            _refresh_chat_memory(chat_id)
            result = turn.to_dict()
            result["chat_id"] = chat_id
            return result
        finally:
            observability.flush()


class WorkflowRequest(BaseModel):
    name: str = "New workflow"
    objective: str = ""
    skills: list[str] = []
    module: str = ""
    environment: Literal["dev", "staging", "prod"] = "prod"
    schedule_cron: str = ""
    enabled: bool = True


class WorkflowPatchRequest(BaseModel):
    name: Optional[str] = None
    objective: Optional[str] = None
    skills: Optional[list[str]] = None
    module: Optional[str] = None
    environment: Optional[Literal["dev", "staging", "prod"]] = None
    schedule_cron: Optional[str] = None
    enabled: Optional[bool] = None


class FindingStatusRequest(BaseModel):
    status: Literal["open", "acknowledged", "resolved"]


@app.get("/api/intelligence/catalog")
def intelligence_catalog() -> dict[str, Any]:
    """Return the workflow-safe skills and the six agent modules for the UI."""
    safe = [
        {
            "name": s.name,
            "category": s.category,
            "description": s.description,
        }
        for s in registry.all()
        if s.name in WORKFLOW_SAFE
    ]
    modules = [
        {
            "key": key,
            "label": spec["label"],
            "description": spec["description"],
            "skills": spec["skills"],
        }
        for key, spec in intel.MODULES.items()
    ]
    return {"skills": safe, "modules": modules}


@app.get("/api/dashboard/summary")
def dashboard_summary(
    project_id: str = DEFAULT_PROJECT_ID,
    time_range: str = "all",
    module: Optional[str] = None,
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
) -> dict[str, Any]:
    """Aggregate counts for the dashboard tiles."""
    _require_project(project_id)
    return intel.dashboard_summary(
        project_id,
        time_range=time_range,
        module=module,
        start_date=start_date,
        end_date=end_date,
    )


@app.get("/api/workflows")
def list_workflows(
    project_id: str = DEFAULT_PROJECT_ID, module: Optional[str] = None
) -> list[dict[str, Any]]:
    """List the workflows configured for a project."""
    _require_project(project_id)
    return intel.list_workflows(project_id, module=module)


@app.post("/api/workflows")
def create_workflow(
    body: WorkflowRequest, project_id: str = DEFAULT_PROJECT_ID
) -> dict[str, Any]:
    """Create a workflow (only read-only diagnose skills are kept)."""
    _require_project(project_id)
    workflow = intel.create_workflow(
        project_id,
        name=body.name,
        skills=body.skills,
        objective=body.objective,
        module=body.module,
        environment=body.environment,
        schedule_cron=body.schedule_cron,
        enabled=body.enabled,
    )
    intel_scheduler.sync_schedules()
    return workflow


@app.patch("/api/workflows/{workflow_id}")
def update_workflow(workflow_id: str, body: WorkflowPatchRequest) -> dict[str, Any]:
    """Update a workflow's fields and re-sync the schedule."""
    workflow = intel.update_workflow(
        workflow_id, **body.model_dump(exclude_none=True)
    )
    if workflow is None:
        raise HTTPException(status_code=404, detail="Workflow not found")
    intel_scheduler.sync_schedules()
    return workflow


@app.delete("/api/workflows/{workflow_id}")
def delete_workflow(workflow_id: str) -> dict[str, bool]:
    """Delete a workflow and its runs/findings."""
    deleted = intel.delete_workflow(workflow_id)
    intel_scheduler.sync_schedules()
    return {"deleted": deleted}


@app.post("/api/workflows/{workflow_id}/run")
def run_workflow_now(
    workflow_id: str,
    user: dict[str, Any] = Depends(auth.require_user),
) -> dict[str, Any]:
    """Queue a workflow to run now — requires a cloud account on the project."""
    from app.core.rbac import assert_capability

    assert_capability(user, "run_workflow")
    workflow = intel.get_workflow(workflow_id)
    if workflow is None:
        raise HTTPException(status_code=404, detail="Workflow not found")
    project_id = workflow["project_id"]
    _require_project(project_id, user)
    azure_ok = connections.status(project_id, "azure").get("connected")
    aws_ok = connections.status(project_id, "aws").get("connected")
    if not (azure_ok or aws_ok):
        raise HTTPException(
            status_code=400,
            detail="Connect an Azure or AWS account for this project before running workflows.",
        )
    run = intel.create_run(workflow_id, trigger="manual")
    if run is None:
        raise HTTPException(status_code=404, detail="Workflow not found")
    try:
        enqueue_run(run["id"])
    except Exception as exc:  # noqa: BLE001 - surface a clean queue error
        intel.mark_run_failed(run["id"], f"Could not enqueue run: {exc}")
        raise HTTPException(
            status_code=503,
            detail=(
                "Could not reach the job queue. Ensure Redis and the worker are "
                f"running. ({exc})"
            ),
        ) from exc
    return run


@app.get("/api/runs")
def list_runs(
    project_id: str = DEFAULT_PROJECT_ID,
    limit: int = 30,
    time_range: str = "all",
    module: Optional[str] = None,
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
) -> list[dict[str, Any]]:
    """List recent workflow runs for a project."""
    _require_project(project_id)
    return intel.list_runs(
        project_id,
        limit=limit,
        module=module,
        time_range=time_range,
        start_date=start_date,
        end_date=end_date,
    )


@app.get("/api/runs/{run_id}")
def get_run(run_id: str) -> dict[str, Any]:
    """Return a run with its findings."""
    run = intel.get_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")
    return run


@app.get("/api/findings")
def list_findings(
    project_id: str = DEFAULT_PROJECT_ID,
    severity: Optional[str] = None,
    skill: Optional[str] = None,
    module: Optional[str] = None,
    status: Optional[str] = None,
    limit: int = 100,
    time_range: str = "all",
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
) -> list[dict[str, Any]]:
    """List findings for a project, optionally filtered."""
    _require_project(project_id)
    return intel.list_findings(
        project_id,
        severity=severity,
        skill=skill,
        module=module,
        status=status,
        limit=limit,
        time_range=time_range,
        start_date=start_date,
        end_date=end_date,
    )


@app.get("/api/architecture/runs")
def list_architecture_runs(
    project_id: str = DEFAULT_PROJECT_ID,
    limit: int = 20,
) -> list[dict[str, Any]]:
    """List Solution Architect runs and ADRs for a project."""
    _require_project(project_id)
    from app.agents.solution_architect.governance import list_runs

    return list_runs(project_id, limit=limit)


@app.patch("/api/findings/{finding_id}")
def update_finding(finding_id: str, body: FindingStatusRequest) -> dict[str, Any]:
    """Acknowledge or resolve a finding."""
    finding = intel.update_finding_status(finding_id, body.status)
    if finding is None:
        raise HTTPException(status_code=404, detail="Finding not found")
    return finding


class ApprovalDecisionRequest(BaseModel):
    decision: Literal["approved", "rejected"]
    decided_by: str = ""


@app.get("/api/approvals")
def list_approvals(
    project_id: str = DEFAULT_PROJECT_ID,
    status: str = "pending",
    limit: int = 100,
    time_range: str = "all",
    module: Optional[str] = None,
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    user: dict[str, Any] = Depends(auth.require_user),
) -> list[dict[str, Any]]:
    """List gated findings awaiting a decision (default: pending), with lineage."""
    _require_project(project_id, user)
    return intel.list_approvals(
        project_id,
        status=status,
        limit=limit,
        module=module,
        time_range=time_range,
        start_date=start_date,
        end_date=end_date,
    )


@app.post("/api/approvals/{approval_id}/decide")
def decide_approval(
    approval_id: str,
    body: ApprovalDecisionRequest,
    user: dict[str, Any] = Depends(auth.require_user),
) -> dict[str, Any]:
    """Approve or reject a gated finding. Nothing executes — the decision is recorded."""
    from app.tenancy import memberships
    from app.platform import break_glass
    from app.core.db import Approval, SessionLocal
    from app.core.rbac import can_approve_gate

    with SessionLocal() as session:
        row = session.get(Approval, approval_id)
        if row is None:
            raise HTTPException(status_code=404, detail="Approval not found")
        gate = row.gate
        project_id = row.project_id
    memberships.assert_project_access(user, project_id)
    bg = break_glass.gate_with_break_glass(project_id=project_id, gate=gate)
    effective_gate = bg.get("gate") if isinstance(bg, dict) else gate
    if body.decision == "approved" and not can_approve_gate(user, effective_gate):
        raise HTTPException(
            status_code=403,
            detail=f"Your role cannot approve gate '{effective_gate}'",
        )
    decided = intel.decide_approval(
        approval_id,
        body.decision,
        body.decided_by or user.get("username") or "",
    )
    if decided is None:
        raise HTTPException(status_code=404, detail="Approval not found")
    return decided


def _frontend_page(name: str) -> FileResponse:
    return FileResponse(_FRONTEND_DIR / name / "index.html")


@app.get("/dashboard")
@app.get("/dashboard/")
def dashboard_page() -> FileResponse:
    return _frontend_page("dashboard")


@app.get("/")
def index() -> FileResponse:
    return FileResponse(_FRONTEND_DIR / "index.html")


@app.get("/c/{chat_id}")
@app.get("/c/{chat_id}/")
def chat_session_page(chat_id: str) -> FileResponse:
    """Serve the chat SPA for a specific conversation id."""
    return FileResponse(_FRONTEND_DIR / "index.html")


@app.get("/settings")
@app.get("/settings/")
def settings_page() -> FileResponse:
    return _frontend_page("settings")


@app.get("/wiki")
@app.get("/wiki/")
def wiki_page() -> FileResponse:
    return _frontend_page("wiki")


@app.get("/login")
@app.get("/login/")
def login_page() -> FileResponse:
    return _frontend_page("login")


@app.get("/organizations")
@app.get("/organizations/")
def organizations_page() -> FileResponse:
    return _frontend_page("organizations")


@app.get("/onboarding")
@app.get("/onboarding/")
def onboarding_page() -> FileResponse:
    return _frontend_page("onboarding")


@app.get("/accept-invite")
@app.get("/accept-invite/")
def accept_invite_page() -> FileResponse:
    return _frontend_page("accept-invite")


@app.get("/approve-member")
@app.get("/approve-member/")
def approve_member_page() -> FileResponse:
    return _frontend_page("approve-member")


app.mount("/", StaticFiles(directory=_FRONTEND_DIR, html=True), name="frontend")
