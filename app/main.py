"""FastAPI application: chatbot, skill catalog, wiki and connection settings."""
import json
import hmac
import os
from contextlib import asynccontextmanager
from datetime import date
from pathlib import Path
from typing import Any, Literal, Optional

from fastapi import FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from app import (
    __version__,
    azure_client,
    chat_memory,
    chats,
    config,
    connections,
    orchestrator,
    projects,
)
from app.db import DEFAULT_PROJECT_ID, init_db
from app.execution import chat_actions
from app.execution import service as execution
from app.intelligence import scheduler as intel_scheduler
from app.intelligence import workflows as intel
from app.intelligence.queue import enqueue_run
from app.presentation import display_value, internal_text
from app.providers import github_infra
from app.skills import WORKFLOW_SAFE, registry

_FRONTEND_DIR = Path(__file__).resolve().parents[1] / "frontend" / "out"


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    intel.seed_default_workflows(DEFAULT_PROJECT_ID)
    intel_scheduler.start_scheduler()
    try:
        yield
    finally:
        intel_scheduler.shutdown_scheduler()


app = FastAPI(title="DevSecOps LLM Skills Suite", version=__version__, lifespan=lifespan)

# Allow browser clients (Next.js live UI on :3000, static export on :8000, etc.).
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


def _refresh_chat_memory(chat_id: str) -> None:
    """Memory is best-effort; a failed refresh must not fail the chat turn."""
    try:
        chat_memory.refresh_memory(chat_id)
    except Exception:
        return


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


def _require_project(project_id: str) -> dict[str, Any]:
    project = projects.get_project(project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    return project


class SkillInfo(BaseModel):
    name: str
    category: str
    description: str
    triggers: list[str]


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
def get_azure_config_route() -> dict[str, Any]:
    """Return Azure OpenAI config (never the key itself, only whether it's set)."""
    azure = config.get_azure_config()
    return {
        "endpoint": azure.endpoint,
        "deployment": azure.deployment,
        "api_version": azure.api_version,
        "configured": azure.configured,
        "has_key": bool(azure.api_key),
    }


@app.put("/api/config/azure-openai")
def put_azure_config_route(body: AzureConfigRequest) -> dict[str, Any]:
    """Save Azure OpenAI config to the database."""
    config.set_azure_config(
        endpoint=body.endpoint,
        api_key=body.api_key,
        deployment=body.deployment,
        api_version=body.api_version,
    )
    return get_azure_config_route()


@app.get("/api/skills", response_model=list[SkillInfo])
def list_skills() -> list[SkillInfo]:
    """Return the catalog of available skills for the UI."""
    return [
        SkillInfo(
            name=s.name,
            category=s.category,
            description=s.description,
            triggers=s.triggers,
        )
        for s in registry.all()
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
    )


@app.get("/api/projects")
def list_projects() -> list[dict[str, Any]]:
    """List all projects (workspaces)."""
    return projects.list_projects()


@app.post("/api/projects")
def create_project(body: ProjectRequest) -> dict[str, Any]:
    """Create a new project, seeded with the starter intelligence workflows."""
    project = projects.create_project(body.name)
    intel.seed_default_workflows(project["id"])
    intel_scheduler.sync_schedules()
    return project


@app.patch("/api/projects/{project_id}")
def rename_project(project_id: str, body: ProjectRequest) -> dict[str, Any]:
    """Rename a project."""
    project = projects.rename_project(project_id, body.name)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    return project


@app.put("/api/projects/{project_id}/default")
def set_default_project(project_id: str) -> dict[str, Any]:
    """Set the sole persisted default project used on a fresh page load."""
    project = projects.set_default(project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    return project


@app.delete("/api/projects/{project_id}")
def delete_project(project_id: str) -> dict[str, bool]:
    """Delete a project and everything scoped to it (the default cannot be deleted)."""
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
def get_project_repos(project_id: str) -> dict[str, Any]:
    """Return the repos mapped to a project plus every repo available to map."""
    _require_project(project_id)
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
def set_project_repos(project_id: str, body: ReposRequest) -> dict[str, Any]:
    """Set which repositories a project is allowed to inspect."""
    project = projects.set_repos(project_id, body.repos)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    return project


@app.get("/api/projects/{project_id}/connections")
def get_connections(project_id: str) -> list[dict[str, Any]]:
    """Return public (secret-free) status of a project's provider connections."""
    _require_project(project_id)
    return connections.all_status(project_id)


@app.get("/api/projects/{project_id}/provider-status")
def get_provider_status(project_id: str, action_scope: Literal["read_only", "write"] = "read_only") -> list[dict[str, Any]]:
    """Return the selected project's provider readiness without secrets."""
    _require_project(project_id)
    return chat_actions.provider_status(project_id, action_scope)


@app.put("/api/projects/{project_id}/connections/{provider}")
def put_connection(project_id: str, provider: str, body: ConnectionRequest) -> dict[str, Any]:
    """Save or update a provider connection within a project."""
    _require_project(project_id)
    if provider not in connections.PROVIDERS:
        raise HTTPException(status_code=404, detail=f"Unknown provider: {provider}")
    return connections.set_connection(project_id, provider, body.method, body.fields)


@app.delete("/api/projects/{project_id}/connections/{provider}")
def delete_connection(project_id: str, provider: str) -> dict[str, Any]:
    """Disconnect a provider within a project."""
    _require_project(project_id)
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
def create_action(body: ActionRequest) -> dict[str, Any]:
    """Persist and dispatch a safe read action, or create a write approval."""
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
def approve_action(action_id: str, body: ActionDecisionRequest) -> dict[str, Any]:
    try:
        return execution.approve_action(action_id, body.approver)
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


def _require_executor(key: Optional[str], provider: Optional[str]) -> str:
    expected = os.environ.get("EXECUTOR_SERVICE_KEY", "dev-executor-key")
    if not key or not hmac.compare_digest(key, expected):
        raise HTTPException(status_code=403, detail="Invalid executor credentials")
    if provider not in {"azure", "aws", "github"}:
        raise HTTPException(status_code=403, detail="Invalid executor provider")
    return provider


@app.get("/internal/execution/jobs/{action_id}/claim")
def claim_action_for_executor(
    action_id: str, provider: str, x_executor_key: Optional[str] = Header(default=None),
    x_executor_provider: Optional[str] = Header(default=None),
) -> dict[str, Any]:
    """Private control-plane endpoint; credentials are never returned publicly."""
    if _require_executor(x_executor_key, x_executor_provider) != provider:
        raise HTTPException(status_code=403, detail="Executor provider mismatch")
    try:
        return execution.claim_for_executor(action_id, provider)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.post("/internal/execution/jobs/{action_id}/events")
def record_executor_event(
    action_id: str, body: ExecutorEventRequest, x_executor_key: Optional[str] = Header(default=None),
    x_executor_provider: Optional[str] = Header(default=None),
) -> dict[str, bool]:
    provider = _require_executor(x_executor_key, x_executor_provider)
    if body.type not in {"action_output", "action_verified"}:
        raise HTTPException(status_code=400, detail="Unsupported executor event")
    try:
        execution.validate_executor_provider(action_id, provider)
        execution.append_event(action_id, body.type, body.payload)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    return {"recorded": True}


@app.get("/internal/execution/jobs/{action_id}/canceled")
def check_executor_cancellation(
    action_id: str, provider: str, x_executor_key: Optional[str] = Header(default=None),
    x_executor_provider: Optional[str] = Header(default=None),
) -> dict[str, bool]:
    if _require_executor(x_executor_key, x_executor_provider) != provider:
        raise HTTPException(status_code=403, detail="Executor provider mismatch")
    try:
        return {"canceled": execution.is_canceled(action_id, provider)}
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc


@app.post("/internal/execution/jobs/{action_id}/result")
def record_executor_result(
    action_id: str, body: ExecutorResultRequest, x_executor_key: Optional[str] = Header(default=None),
    x_executor_provider: Optional[str] = Header(default=None),
) -> dict[str, bool]:
    provider = _require_executor(x_executor_key, x_executor_provider)
    try:
        execution.validate_executor_provider(action_id, provider)
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


@app.post("/api/chat/stream")
def chat_stream(request: ChatRequest) -> StreamingResponse:
    """Stream an orchestrated chat turn as Server-Sent Events."""
    if request.skill and registry.get(request.skill) is None:
        raise HTTPException(status_code=400, detail=f"Unknown skill: {request.skill}")

    chat_id = request.chat_id
    # UI may say mlife / ml-*; tools and skills still need EQIP / eq-*.
    internal_message = internal_text(request.message)
    if not chat_id or chats.get_chat(chat_id) is None:
        chat_id = chats.create_chat(request.message, project_id=request.project_id)["id"]
    if request.edit_message_id:
        if not chats.replace_user_message(chat_id, request.edit_message_id, request.message):
            raise HTTPException(status_code=404, detail="User message not found")
    else:
        chats.add_message(chat_id, "user", request.message)

    special_action: Optional[dict[str, Any]] = None
    if request.mode == "agent":
        try:
            special_action = chat_actions.handle_turn(
                chat_id, request.project_id, internal_message, request.action_scope, request.access_level
            )
        except ValueError as exc:
            special_action = {
                "reply": f"I could not prepare that Azure action: {exc}",
                "action": None,
                "event_type": "action_failed",
            }

    def sse(event: dict[str, Any]) -> str:
        return f"data: {json.dumps(display_value(event), default=str)}\n\n"

    def generate() -> Any:
        yield sse({"type": "chat", "chat_id": chat_id})

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
            _refresh_chat_memory(chat_id)
            yield sse({
                "type": "final",
                "mode": "agent",
                "reply": reply,
                "chat_id": chat_id,
                **({"required_action_scope": special_action["required_action_scope"]} if special_action.get("required_action_scope") else {}),
                **({"action_id": action["id"], "action": action} if action else {}),
            })
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
            _refresh_chat_memory(chat_id)
            yield sse({"type": "final", "mode": request.mode, "reply": reply, "chat_id": chat_id})
            return

        history = chat_memory.get_model_context(
            chat_id, internal_message, project_id=request.project_id
        )
        diagnostic_context = chat_actions.action_diagnostic_context(chat_id, internal_message)
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

        reply = final.get("reply", "")
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
        _refresh_chat_memory(chat_id)
        final["chat_id"] = chat_id
        yield sse({"type": "final", **final})

    return StreamingResponse(generate(), media_type="text/event-stream")


@app.post("/api/chat/execute-plan")
def execute_plan(request: ExecutePlanRequest) -> StreamingResponse:
    """Execute a plan the user approved (from plan mode), streaming the run."""
    chat = chats.get_chat(request.chat_id)
    if chat is None:
        raise HTTPException(status_code=404, detail="Chat not found")

    steps = [
        orchestrator.PlanStep(skill=s.skill, objective=s.objective)
        for s in request.steps
        if registry.get(s.skill) is not None
    ]
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

    def sse(event: dict[str, Any]) -> str:
        return f"data: {json.dumps(display_value(event), default=str)}\n\n"

    def generate() -> Any:
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
        _refresh_chat_memory(chat_id)
        final["chat_id"] = chat_id
        yield sse({"type": "final", **final})

    return StreamingResponse(generate(), media_type="text/event-stream")


@app.post("/api/chat")
def chat(request: ChatRequest) -> dict[str, Any]:
    """Run one orchestrated chat turn, persisting both messages to the chat."""
    if request.skill and registry.get(request.skill) is None:
        raise HTTPException(status_code=400, detail=f"Unknown skill: {request.skill}")

    chat_id = request.chat_id
    if not chat_id or chats.get_chat(chat_id) is None:
        chat_id = chats.create_chat(request.message, project_id=request.project_id)["id"]

    if request.edit_message_id:
        if not chats.replace_user_message(chat_id, request.edit_message_id, request.message):
            raise HTTPException(status_code=404, detail="User message not found")
    else:
        chats.add_message(chat_id, "user", request.message)

    if request.mode == "agent":
        try:
            special_action = chat_actions.handle_turn(
                chat_id, request.project_id, request.message, request.action_scope, request.access_level
            )
        except ValueError as exc:
            special_action = {"reply": f"I could not prepare that Azure action: {exc}", "action": None}
        if special_action is not None:
            reply = str(special_action.get("reply", ""))
            action = special_action.get("action")
            meta = {"mode": "agent"}
            if action:
                meta.update({"action_id": action["id"], "action_status": action.get("status")})
            if special_action.get("pending_resource_group_name"):
                meta["pending_resource_group_name"] = special_action["pending_resource_group_name"]
            if special_action.get("pending_action_spec"):
                meta["pending_action_spec"] = special_action["pending_action_spec"]
            chats.add_message(chat_id, "assistant", reply, meta)
            _refresh_chat_memory(chat_id)
            result = {"mode": "agent", "reply": reply, "chat_id": chat_id}
            if special_action.get("required_action_scope"):
                result["required_action_scope"] = special_action["required_action_scope"]
            if action:
                result.update({"action_id": action["id"], "action": action})
            return result

    if not config.get_azure_config().configured:
        reply = (
            "Azure OpenAI is not configured yet. Open Settings and add your "
            "Azure OpenAI endpoint and key. Chats, skills and wiki work offline "
            "so you can still preview the suite.\n\n"
            + chat_actions.provider_status_text(request.project_id, request.action_scope)
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
    diagnostic_context = chat_actions.action_diagnostic_context(chat_id, request.message)
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
        )
    except azure_client.AzureOpenAINotConfiguredError as exc:
        turn = orchestrator.ChatTurn(mode=request.mode, reply=str(exc))

    chats.add_message(
        chat_id,
        "assistant",
        turn.reply,
        {"mode": turn.mode, "skills_used": turn.skills_used, "charts": turn.charts},
    )
    _refresh_chat_memory(chat_id)
    result = turn.to_dict()
    result["chat_id"] = chat_id
    return result


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
def run_workflow_now(workflow_id: str) -> dict[str, Any]:
    """Queue a workflow to run now."""
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
) -> list[dict[str, Any]]:
    """List gated findings awaiting a decision (default: pending), with lineage."""
    _require_project(project_id)
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
def decide_approval(approval_id: str, body: ApprovalDecisionRequest) -> dict[str, Any]:
    """Approve or reject a gated finding. Nothing executes — the decision is recorded."""
    decided = intel.decide_approval(approval_id, body.decision, body.decided_by)
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


@app.get("/settings")
@app.get("/settings/")
def settings_page() -> FileResponse:
    return _frontend_page("settings")


@app.get("/wiki")
@app.get("/wiki/")
def wiki_page() -> FileResponse:
    return _frontend_page("wiki")


app.mount("/", StaticFiles(directory=_FRONTEND_DIR, html=True), name="frontend")
