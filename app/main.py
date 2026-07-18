"""FastAPI application: chatbot, skill catalog, wiki and connection settings."""
import json
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Literal, Optional

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from app import (
    __version__,
    azure_client,
    chats,
    config,
    connections,
    orchestrator,
    projects,
)
from app.db import DEFAULT_PROJECT_ID, init_db
from app.intelligence import scheduler as intel_scheduler
from app.intelligence import workflows as intel
from app.intelligence.queue import enqueue_run
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


class ExecutePlanRequest(BaseModel):
    chat_id: str
    project_id: str = DEFAULT_PROJECT_ID
    steps: list[PlanStepRequest] = []
    action_scope: Literal["read_only", "write"] = "read_only"
    access_level: Literal["ask_approval", "auto_approve", "full_access"] = "ask_approval"


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


@app.delete("/api/projects/{project_id}")
def delete_project(project_id: str) -> dict[str, bool]:
    """Delete a project and everything scoped to it (the default cannot be deleted)."""
    deleted = projects.delete_project(project_id)
    if deleted:
        intel_scheduler.sync_schedules()
    return {"deleted": deleted}


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
    if not chat_id or chats.get_chat(chat_id) is None:
        chat_id = chats.create_chat(request.message, project_id=request.project_id)["id"]
    if request.edit_message_id:
        if not chats.replace_user_message(chat_id, request.edit_message_id, request.message):
            raise HTTPException(status_code=404, detail="User message not found")
    else:
        chats.add_message(chat_id, "user", request.message)

    def sse(event: dict[str, Any]) -> str:
        return f"data: {json.dumps(event)}\n\n"

    def generate() -> Any:
        yield sse({"type": "chat", "chat_id": chat_id})

        if not config.get_azure_config().configured:
            reply = (
                "Azure OpenAI is not configured yet. Open Settings and add your "
                "Azure OpenAI endpoint and key. Chats, skills and wiki work "
                "offline so you can still preview the suite."
            )
            yield sse({"type": "delta", "text": reply})
            chats.add_message(chat_id, "assistant", reply, {"mode": request.mode})
            yield sse({"type": "final", "mode": request.mode, "reply": reply, "chat_id": chat_id})
            return

        history = chats.get_history(chat_id)
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
    if not steps:
        raise HTTPException(status_code=400, detail="No runnable steps in the plan")

    chat_id = request.chat_id

    def sse(event: dict[str, Any]) -> str:
        return f"data: {json.dumps(event)}\n\n"

    def generate() -> Any:
        yield sse({"type": "chat", "chat_id": chat_id})

        if not config.get_azure_config().configured:
            reply = "Azure OpenAI is not configured yet. Open Settings to run plans."
            yield sse({"type": "delta", "text": reply})
            chats.add_message(chat_id, "assistant", reply, {"mode": "agent"})
            yield sse({"type": "final", "mode": "agent", "reply": reply, "chat_id": chat_id})
            return

        history = chats.get_history(chat_id)
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

    if not config.get_azure_config().configured:
        reply = (
            "Azure OpenAI is not configured yet. Open Settings and add your "
            "Azure OpenAI endpoint and key. Chats, skills and wiki work offline "
            "so you can still preview the suite."
        )
        turn = orchestrator.ChatTurn(mode=request.mode, reply=reply)
        chats.add_message(chat_id, "assistant", reply, {"mode": request.mode})
        result = turn.to_dict()
        result["chat_id"] = chat_id
        return result

    history = chats.get_history(chat_id)
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
        {"key": key, "label": spec["label"], "skills": spec["skills"]}
        for key, spec in intel.MODULES.items()
    ]
    return {"skills": safe, "modules": modules}


@app.get("/api/dashboard/summary")
def dashboard_summary(project_id: str = DEFAULT_PROJECT_ID) -> dict[str, Any]:
    """Aggregate counts for the dashboard tiles."""
    _require_project(project_id)
    return intel.dashboard_summary(project_id)


@app.get("/api/workflows")
def list_workflows(project_id: str = DEFAULT_PROJECT_ID) -> list[dict[str, Any]]:
    """List the workflows configured for a project."""
    _require_project(project_id)
    return intel.list_workflows(project_id)


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
def list_runs(project_id: str = DEFAULT_PROJECT_ID, limit: int = 30) -> list[dict[str, Any]]:
    """List recent workflow runs for a project."""
    _require_project(project_id)
    return intel.list_runs(project_id, limit=limit)


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
    project_id: str = DEFAULT_PROJECT_ID, status: str = "pending", limit: int = 100
) -> list[dict[str, Any]]:
    """List gated findings awaiting a decision (default: pending), with lineage."""
    _require_project(project_id)
    return intel.list_approvals(project_id, status=status, limit=limit)


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
