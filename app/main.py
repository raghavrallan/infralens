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
from app.providers import github_infra
from app.skills import registry

_STATIC_DIR = Path(__file__).parent / "static"


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    yield


app = FastAPI(title="DevSecOps LLM Skills Suite", version=__version__, lifespan=lifespan)


class ChatRequest(BaseModel):
    message: str
    chat_id: Optional[str] = None
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
    """Create a new project."""
    return projects.create_project(body.name)


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
    return {"deleted": projects.delete_project(project_id)}


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
            {"mode": final.get("mode"), "skills_used": final.get("skills_used", [])},
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
            {"mode": final.get("mode", "agent"), "skills_used": final.get("skills_used", [])},
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
        {"mode": turn.mode, "skills_used": turn.skills_used},
    )
    result = turn.to_dict()
    result["chat_id"] = chat_id
    return result


@app.get("/")
def index() -> FileResponse:
    return FileResponse(_STATIC_DIR / "index.html")


@app.get("/settings")
def settings_page() -> FileResponse:
    return FileResponse(_STATIC_DIR / "settings.html")


@app.get("/wiki")
def wiki_page() -> FileResponse:
    return FileResponse(_STATIC_DIR / "wiki.html")


app.mount("/static", StaticFiles(directory=_STATIC_DIR), name="static")
