"""Engineering workflow APIs: context, tasks, artifacts, memory, recommendations."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel

from app.core import auth
from app.core.db import DEFAULT_PROJECT_ID
from app.core.rbac import assert_capability
from app.platform.engineering import activity, artifacts as artifact_store
from app.platform.engineering import context as eng_context
from app.platform.engineering import generate, health, knowledge, tasks as task_store
from app.tenancy import memberships, projects

router = APIRouter()


def _project(user: dict[str, Any], project_id: str) -> str:
    memberships.assert_project_access(user, project_id)
    if projects.get_project(project_id) is None:
        raise HTTPException(status_code=404, detail="Project not found")
    return project_id


class TaskTransitionRequest(BaseModel):
    status: str
    comment: str = ""


class EvidenceRequest(BaseModel):
    name: str
    note: str = ""


class MemoryStatusRequest(BaseModel):
    status: str


class MemorySupersedeRequest(BaseModel):
    summary: str


class GenerateArtifactRequest(BaseModel):
    kind: str = "terraform"


class AcceptRecommendationRequest(BaseModel):
    project_id: str = DEFAULT_PROJECT_ID
    title: str
    reason: str = ""
    stage: str = "infrastructure"
    related_task_id: str = ""
    action: str = ""


class RequirementAnswerRequest(BaseModel):
    project_id: str = DEFAULT_PROJECT_ID
    question: str
    answer: str
    category: str = "clarification"


@router.get("/api/engineering/context")
def get_context(
    project_id: str = DEFAULT_PROJECT_ID,
    user: dict[str, Any] = Depends(auth.require_user),
) -> dict[str, Any]:
    _project(user, project_id)
    return eng_context.project_context(project_id)


@router.get("/api/engineering/health")
def get_health(
    project_id: str = DEFAULT_PROJECT_ID,
    user: dict[str, Any] = Depends(auth.require_user),
) -> dict[str, Any]:
    _project(user, project_id)
    return health.build_health(project_id)


@router.get("/api/engineering/tasks")
def get_tasks(
    project_id: str = DEFAULT_PROJECT_ID,
    delivery_run_id: str = "",
    user: dict[str, Any] = Depends(auth.require_user),
) -> list[dict[str, Any]]:
    _project(user, project_id)
    return task_store.list_tasks(project_id, delivery_run_id)


@router.post("/api/engineering/tasks/{task_id}/transition")
def post_task_transition(
    task_id: str,
    body: TaskTransitionRequest,
    user: dict[str, Any] = Depends(auth.require_user),
) -> dict[str, Any]:
    task = task_store.get_task(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")
    _project(user, task["project_id"])
    if body.status in {"approved", "completed"}:
        assert_capability(user, "approve_human")
    else:
        assert_capability(user, "propose_write")
    try:
        return task_store.transition(
            task_id,
            body.status,
            actor=user.get("username") or "",
            comment=body.comment,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/api/engineering/tasks/{task_id}/evidence")
def post_evidence(
    task_id: str,
    body: EvidenceRequest,
    user: dict[str, Any] = Depends(auth.require_user),
) -> dict[str, Any]:
    task = task_store.get_task(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")
    _project(user, task["project_id"])
    assert_capability(user, "propose_write")
    return task_store.add_evidence(
        task_id, name=body.name, note=body.note, actor=user.get("username") or ""
    )


@router.post("/api/engineering/artifacts/upload")
async def upload_artifact(
    project_id: str = Form(DEFAULT_PROJECT_ID),
    task_id: str = Form(""),
    delivery_run_id: str = Form(""),
    file: UploadFile = File(...),
    user: dict[str, Any] = Depends(auth.require_user),
) -> dict[str, Any]:
    _project(user, project_id)
    assert_capability(user, "propose_write")
    data = await file.read()
    if len(data) > 2_000_000:
        raise HTTPException(status_code=400, detail="File too large (2 MB limit)")
    saved = artifact_store.save_upload(
        project_id=project_id,
        filename=file.filename or "upload",
        data=data,
        mime=file.content_type or "",
        task_id=task_id,
        delivery_run_id=delivery_run_id,
        created_by=user.get("username") or "",
    )
    activity.record(
        project_id,
        "artifact_uploaded",
        actor=user.get("username") or "",
        detail=file.filename or "upload",
        ref_type="artifact",
        ref_id=saved["id"],
    )
    return saved


@router.get("/api/engineering/artifacts")
def get_artifacts(
    project_id: str = DEFAULT_PROJECT_ID,
    task_id: str = "",
    user: dict[str, Any] = Depends(auth.require_user),
) -> list[dict[str, Any]]:
    _project(user, project_id)
    return artifact_store.list_artifacts(project_id, task_id=task_id)


@router.get("/api/engineering/artifacts/{artifact_id}")
def get_artifact(
    artifact_id: str,
    user: dict[str, Any] = Depends(auth.require_user),
) -> dict[str, Any]:
    row = artifact_store.get_artifact(artifact_id, full=True)
    if row is None:
        raise HTTPException(status_code=404, detail="Artifact not found")
    _project(user, row["project_id"])
    return row


@router.post("/api/engineering/artifacts/{artifact_id}/validate")
def post_validate(
    artifact_id: str,
    user: dict[str, Any] = Depends(auth.require_user),
) -> dict[str, Any]:
    row = artifact_store.get_artifact(artifact_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Artifact not found")
    _project(user, row["project_id"])
    return artifact_store.validate_artifact(artifact_id)


@router.post("/api/engineering/tasks/{task_id}/generate")
def generate_for_task(
    task_id: str,
    body: GenerateArtifactRequest,
    user: dict[str, Any] = Depends(auth.require_user),
) -> dict[str, Any]:
    task = task_store.get_task(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")
    _project(user, task["project_id"])
    assert_capability(user, "propose_write")
    required = task.get("required_artifacts") or [{"name": "main.tf", "kind": body.kind}]
    saved = []
    for spec in required:
        name = spec.get("name") if isinstance(spec, dict) else str(spec)
        kind = (spec.get("kind") if isinstance(spec, dict) else body.kind) or body.kind
        from app.platform.engineering.iac_generate import generate_artifact_content

        content = generate_artifact_content(
            name=name or "artifact",
            kind=kind,
            title=task["title"],
            description=str(task.get("description") or ""),
            project_id=task["project_id"],
            delivery_run_id=str(task.get("delivery_run_id") or ""),
        )
        saved.append(
            artifact_store.save_artifact(
                project_id=task["project_id"],
                name=name,
                filename=name,
                kind=kind,
                origin="generated",
                content_text=content,
                task_id=task_id,
                delivery_run_id=task.get("delivery_run_id") or "",
                created_by=user.get("username") or "",
            )
        )
    activity.record(
        task["project_id"],
        "artifact_generated",
        actor=user.get("username") or "",
        detail=task["title"],
        ref_type="task",
        ref_id=task_id,
    )
    workspace = {}
    if task.get("delivery_run_id"):
        try:
            from app.platform.engineering import iac_workspace

            workspace = iac_workspace.sync(task["project_id"], str(task["delivery_run_id"]))
        except Exception:
            workspace = {}
    return {"task": task_store.get_task(task_id), "artifacts": saved, "workspace": workspace}


@router.get("/api/engineering/memory")
def get_memory(
    project_id: str = DEFAULT_PROJECT_ID,
    category: str = "",
    status: str = "",
    q: str = "",
    limit: int = 80,
    user: dict[str, Any] = Depends(auth.require_user),
) -> list[dict[str, Any]]:
    _project(user, project_id)
    return knowledge.list_knowledge(project_id, category=category, status=status, query=q, limit=limit)


@router.post("/api/engineering/memory/{item_id}/status")
def post_memory_status(
    item_id: str,
    body: MemoryStatusRequest,
    user: dict[str, Any] = Depends(auth.require_user),
) -> dict[str, Any]:
    item = knowledge.get_item(item_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Memory entry not found")
    _project(user, item["project_id"])
    if body.status in {"archived", "superseded"}:
        assert_capability(user, "archive_memory")
    else:
        assert_capability(user, "verify_memory")
    try:
        updated = knowledge.set_status(item_id, body.status, actor=user.get("username") or "")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    activity.record(
        item["project_id"],
        f"memory_{body.status}",
        actor=user.get("username") or "",
        detail=item.get("summary") or "",
        ref_type="memory",
        ref_id=item_id,
    )
    return updated


@router.post("/api/engineering/memory/{item_id}/supersede")
def post_supersede(
    item_id: str,
    body: MemorySupersedeRequest,
    user: dict[str, Any] = Depends(auth.require_user),
) -> dict[str, Any]:
    item = knowledge.get_item(item_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Memory entry not found")
    _project(user, item["project_id"])
    assert_capability(user, "archive_memory")
    return knowledge.supersede(item_id, summary=body.summary, actor=user.get("username") or "")


@router.post("/api/engineering/recommendations/accept")
def accept_recommendation(
    body: AcceptRecommendationRequest,
    user: dict[str, Any] = Depends(auth.require_user),
) -> dict[str, Any]:
    _project(user, body.project_id)
    assert_capability(user, "propose_write")
    action = (body.action or "").strip()
    if action == "generate_terraform" or body.title.lower().startswith("generate terraform"):
        from app.platform.engineering.iac_generate import generate_missing_for_project

        result = generate_missing_for_project(
            body.project_id, actor=user.get("username") or ""
        )
        activity.record(
            body.project_id,
            "artifacts_generated",
            actor=user.get("username") or "",
            detail=f"{result.get('count') or 0} artifacts from recommendation",
            ref_type="project",
            ref_id=body.project_id,
        )
        return {"action": "generate_terraform", **result}
    task = task_store.create_task(
        project_id=body.project_id,
        title=body.title or "Follow-up task",
        description=body.reason,
        stage=body.stage,
        ai_recommendation=body.reason,
    )
    activity.record(
        body.project_id,
        "recommendation_accepted",
        actor=user.get("username") or "",
        detail=task["title"],
        ref_type="task",
        ref_id=task["id"],
    )
    return task


@router.post("/api/engineering/requirements/answer")
def answer_requirement(
    body: RequirementAnswerRequest,
    user: dict[str, Any] = Depends(auth.require_user),
) -> dict[str, Any]:
    _project(user, body.project_id)
    assert_capability(user, "propose_write")
    req_id = generate._save_requirement(
        project_id=body.project_id,
        category=body.category,
        title=body.question[:400],
        statement=body.answer,
        source="user",
    )
    knowledge.remember(
        project_id=body.project_id,
        summary=f"{body.question}: {body.answer}",
        kind="requirement",
        category="requirement",
        confidence="high",
        status="verified",
        source="user",
        created_by=user.get("username") or "",
        extra={"requirement_id": req_id},
    )
    return {"id": req_id, "ok": True}


def _stub_artifact(kind: str, name: str, title: str, description: str) -> str:
    from app.platform.engineering.iac_generate import generate_artifact_content

    return generate_artifact_content(
        name=name,
        kind=kind,
        title=title,
        description=description,
        project_id="",
    )
