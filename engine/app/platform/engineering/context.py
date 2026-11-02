"""Assemble the shared project context used by agents and the dashboard."""
from __future__ import annotations

from typing import Any

from app.platform.engineering import activity, artifacts as artifact_store
from app.platform.engineering import generate, health, knowledge, tasks as task_store
from app.platform.memory import list_precedent


def project_context(project_id: str) -> dict[str, Any]:
    tasks = task_store.list_tasks(project_id)
    snapshot = health.build_health(project_id)
    memory_ctx = knowledge.architect_context(project_id)
    return {
        "project_id": project_id,
        "requirements": generate.list_requirements(project_id),
        "tasks": tasks,
        "artifacts": artifact_store.list_artifacts(project_id),
        "memory": knowledge.list_knowledge(project_id, limit=40),
        "memory_for_architect": memory_ctx,
        "activity": activity.list_activity(project_id),
        "health": snapshot,
        "precedent": list_precedent(project_id, limit=8),
    }


def architect_seed(project_id: str, extra: str = "") -> str:
    ctx = knowledge.architect_context(project_id)
    docs = []
    for artifact in artifact_store.list_artifacts(project_id)[:8]:
        if artifact.get("kind") in {"document", "terraform", "yaml"} and artifact.get("content_text"):
            docs.append(f"### {artifact.get('filename') or artifact.get('name')}\n{artifact['content_text'][:4000]}")
    parts = [ctx.get("prompt") or "", extra or "", "\n\n".join(docs)]
    return "\n\n".join(part for part in parts if part).strip()
