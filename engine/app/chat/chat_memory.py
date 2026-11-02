"""Bounded, redacted memory for reliable same-chat follow-ups.

The complete transcript remains persisted for the UI and audit history. This
module creates a much smaller context block for model calls so long chats do
not crowd out the current request or leak facts between projects.
"""
import json
import re
from typing import Any, Optional

from app.core import azure_client
from app.core.db import Chat, ChatMemory, Message, SessionLocal
from sqlalchemy import delete, select

MAX_SUMMARY_CHARS = 2400
MAX_ITEM_CHARS = 600
MAX_ITEMS = 16
MAX_CONTEXT_CHARS = 10000
MAX_SOURCE_CHARS = 18000
MAX_RECENT_TURNS = 6
MAX_RECENT_ITEM_CHARS = 1800
MAX_RECENT_CONTEXT_CHARS = 7000

_SECRET_KEY = re.compile(
    r"(?i)(client[_ -]?secret|secret[_ -]?access[_ -]?key|access[_ -]?token|"
    r"refresh[_ -]?token|api[_ -]?key|password|authorization|gh[_ -]?token|"
    r"private[_ -]?key)"
)
_SECRET_ASSIGNMENT = re.compile(
    r"(?i)(\b(?:client[_ -]?secret|secret[_ -]?access[_ -]?key|access[_ -]?token|"
    r"refresh[_ -]?token|api[_ -]?key|password|authorization|gh[_ -]?token|"
    r"private[_ -]?key)\b\s*[:=]\s*)([^\s,;]+)"
)
_BEARER = re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/=-]+")
_LONG_TOKEN = re.compile(r"\b[A-Za-z0-9+/=_-]{32,}\b")
_SECRET_FLAG = re.compile(
    r"(?i)^--?(?:client[-_ ]?secret|secret[-_ ]?access[-_ ]?key|access[-_ ]?token|"
    r"refresh[-_ ]?token|api[-_ ]?key|password|authorization|gh[-_ ]?token|private[-_ ]?key)$"
)

MEMORY_SYSTEM_PROMPT = """You maintain compact memory for one DevSecOps chat.
Extract only facts explicitly supported by the transcript. Preserve concrete
resources, repositories, metrics, chart requests, regions, findings, pending
questions, decisions, action IDs, infrastructure requirements, components
discussed/planned/deployed, and deployment outcomes. Do not invent values.
Never store credentials, tokens, keys, passwords, or authorization headers.
Return only JSON with this shape:
{"summary":"", "facts":[], "references":[], "unresolved":[],
 "requirements":[], "infra_state":{"discussed":[], "planned":[], "deployed":[]},
 "deployment_outcomes":[]}.
requirements: durable user goals for infra/app delivery.
infra_state.discussed/planned/deployed: short component labels.
deployment_outcomes: short outcome lines like "action_id=... succeeded|failed".
Keep each item concise."""


def _memory_system_prompt() -> str:
    from app.core.prompts import get_text_prompt

    return get_text_prompt(
        "chat-memory-system",
        fallback=MEMORY_SYSTEM_PROMPT,
    )


def redact(value: Any) -> Any:
    """Redact secret-like values recursively before persistence or model use."""
    if isinstance(value, dict):
        return {
            str(key): "[REDACTED]" if _SECRET_KEY.search(str(key)) else redact(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        redacted: list[Any] = []
        redact_next = False
        for item in value:
            if redact_next:
                redacted.append("[REDACTED]")
                redact_next = False
            else:
                redacted.append(redact(item))
            if isinstance(item, str) and _SECRET_FLAG.fullmatch(item.strip()):
                redact_next = True
        return redacted
    if not isinstance(value, str):
        return value
    value = _SECRET_ASSIGNMENT.sub(r"\1[REDACTED]", value)
    value = _BEARER.sub("Bearer [REDACTED]", value)
    # Long opaque values are almost always credentials in chat evidence. Do
    # not apply this to ordinary short resource names or UUIDs.
    return _LONG_TOKEN.sub(
        lambda match: "[REDACTED]" if not re.fullmatch(
            r"[0-9a-f-]{36}", match.group(0), re.IGNORECASE
        ) else match.group(0),
        value,
    )


def _clip(value: Any, limit: int = MAX_ITEM_CHARS) -> str:
    text = " ".join(str(value or "").split())
    return redact(text)[:limit].rstrip()


def _clean_items(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    result: list[str] = []
    for item in value[:MAX_ITEMS]:
        text = _clip(item)
        if text and text not in result:
            result.append(text)
    return result


def _normalise_infra_state(value: Any) -> dict[str, list[str]]:
    raw = value if isinstance(value, dict) else {}
    return {
        "discussed": _clean_items(raw.get("discussed")),
        "planned": _clean_items(raw.get("planned")),
        "deployed": _clean_items(raw.get("deployed")),
    }


def _normalise(parsed: Any) -> dict[str, Any]:
    parsed = parsed if isinstance(parsed, dict) else {}
    return {
        "summary": _clip(parsed.get("summary"), MAX_SUMMARY_CHARS),
        "facts": _clean_items(parsed.get("facts")),
        "references": _clean_items(parsed.get("references")),
        "unresolved": _clean_items(parsed.get("unresolved")),
        "requirements": _clean_items(parsed.get("requirements")),
        "infra_state": _normalise_infra_state(parsed.get("infra_state")),
        "deployment_outcomes": _clean_items(parsed.get("deployment_outcomes")),
    }


def _transcript(chat_id: str) -> tuple[Optional[Chat], list[dict[str, Any]]]:
    with SessionLocal() as session:
        chat = session.get(Chat, chat_id)
        if chat is None:
            return None, []
        rows = session.execute(
            select(Message)
            .where(Message.chat_id == chat_id)
            .order_by(Message.created_at.asc(), Message.id.asc())
        ).scalars()
        messages = [
            {"role": row.role, "content": row.content, "meta": row.meta or {}}
            for row in rows
        ]
        return chat, messages


def get_memory(chat_id: str) -> Optional[dict[str, Any]]:
    """Load memory only when it belongs to the chat's current project."""
    try:
        with SessionLocal() as session:
            chat = session.get(Chat, chat_id)
            memory = session.get(ChatMemory, chat_id)
            if chat is None or memory is None or memory.project_id != chat.project_id:
                return None
            return {
                "chat_id": memory.chat_id,
                "project_id": memory.project_id,
                "summary": memory.summary or "",
                "facts": memory.facts or [],
                "references": memory.references or [],
                "unresolved": memory.unresolved or [],
                "requirements": getattr(memory, "requirements", None) or [],
                "infra_state": getattr(memory, "infra_state", None)
                or {
                    "discussed": [],
                    "planned": [],
                    "deployed": [],
                },
                "deployment_outcomes": getattr(memory, "deployment_outcomes", None) or [],
                "source_message_count": memory.source_message_count,
                "version": memory.version,
            }
    except Exception:  # noqa: BLE001 - schema lag must not break chat routing
        return None


def render_model_context(
    memory: Optional[dict[str, Any]], current_message: str = ""
) -> list[dict[str, str]]:
    """Render only compact memory plus the current user turn for the model."""
    blocks: list[str] = []
    if memory:
        lines = [
            "CHAT MEMORY (same chat and project; use only to resolve follow-ups):",
            f"Summary: {_clip(memory.get('summary'), MAX_SUMMARY_CHARS)}",
        ]
        for label, key in (
            ("Facts", "facts"),
            ("References", "references"),
            ("Unresolved items", "unresolved"),
            ("Requirements", "requirements"),
            ("Deployment outcomes", "deployment_outcomes"),
        ):
            items = _clean_items(memory.get(key))
            if items:
                lines.append(f"{label}:")
                lines.extend(f"- {item}" for item in items)
        infra_state = memory.get("infra_state") if isinstance(memory.get("infra_state"), dict) else {}
        for label, key in (
            ("Infra discussed", "discussed"),
            ("Infra planned", "planned"),
            ("Infra deployed", "deployed"),
        ):
            items = _clean_items(infra_state.get(key))
            if items:
                lines.append(f"{label}:")
                lines.extend(f"- {item}" for item in items)
        blocks.append("\n".join(lines))
    current = _clip(current_message, MAX_CONTEXT_CHARS)
    messages: list[dict[str, str]] = []
    if blocks:
        messages.append({"role": "system", "content": blocks[0][:MAX_CONTEXT_CHARS]})
    if current:
        messages.append({"role": "user", "content": current})
    return messages


def render_recent_context(
    transcript: list[dict[str, Any]], current_message: str = ""
) -> str:
    """Render a small, redacted slice of the latest conversation turns.

    A compact summary can omit the exact resource, metric, or time window
    needed by a terse follow-up. Keep recent concrete turns in a separate
    bounded block so live-data routing can resolve those references.
    """
    items = list(transcript)
    current = " ".join(str(current_message or "").split())
    if current:
        # The current user message is rendered separately below. Remove only
        # the last matching transcript item; an earlier identical request may
        # still be useful historical context.
        for index in range(len(items) - 1, -1, -1):
            item = items[index]
            if item.get("role") != "user":
                continue
            content = " ".join(str(item.get("content") or "").split())
            if content == current:
                items.pop(index)
                break

    recent = [
        item
        for item in items[-MAX_RECENT_TURNS:]
        if item.get("role") in {"user", "assistant"} and item.get("content")
    ]
    if not recent:
        return ""

    lines = [
        "RECENT CHAT TURNS (same chat and project; resolve references from these exact details):"
    ]
    for item in recent:
        role = "User" if item.get("role") == "user" else "Assistant"
        lines.append(f"{role}: {_clip(item.get('content'), MAX_RECENT_ITEM_CHARS)}")
    return "\n".join(lines)[:MAX_RECENT_CONTEXT_CHARS].rstrip()


def _project_engineering_memory(project_id: Optional[str]) -> str:
    """Project-level decisions/tasks so chat skills can recall prior architecture."""
    if not project_id:
        return ""
    try:
        from app.platform.engineering import tasks as task_store
        from app.platform.engineering.knowledge import architect_context

        ctx = architect_context(project_id)
        prompt = str(ctx.get("prompt") or "").strip()
        tasks = task_store.list_tasks(project_id)
        done = sum(1 for item in tasks if item.get("status") == "completed")
        titles = ", ".join(str(item.get("title") or "") for item in tasks[:12] if item.get("title"))
        parts = [prompt] if prompt else []
        if tasks:
            parts.append(f"DELIVERY CHECKLIST: {done}/{len(tasks)} completed. {titles}")
        return "\n".join(parts).strip()
    except Exception:
        return ""


def get_model_context(
    chat_id: str,
    current_message: Optional[str] = None,
    system_blocks: Optional[list[str]] = None,
    project_id: Optional[str] = None,
) -> list[dict[str, str]]:
    """Return bounded memory, recent turns, and the current turn."""
    memory = get_memory(chat_id)
    if project_id and memory and memory.get("project_id") != project_id:
        memory = None
    _, transcript = _transcript(chat_id)
    if current_message is None:
        messages = transcript
        current_message = next(
            (item["content"] for item in reversed(messages) if item["role"] == "user"),
            "",
        )
    result = render_model_context(memory, current_message)
    project_block = _project_engineering_memory(project_id)
    if project_block:
        result.insert(0, {"role": "system", "content": _clip(project_block, MAX_CONTEXT_CHARS)})
    recent = render_recent_context(transcript, current_message)
    if recent:
        recent_message = {"role": "system", "content": recent}
        if result and result[-1].get("role") == "user":
            result = result[:-1] + [recent_message, result[-1]]
        else:
            result.append(recent_message)
    for block in system_blocks or []:
        if block:
            result.insert(0, {"role": "system", "content": _clip(block, MAX_CONTEXT_CHARS)})
    return result


def _fallback(messages: list[dict[str, Any]]) -> dict[str, Any]:
    latest = messages[-4:]
    compact = [
        f"{item.get('role', 'message')}: {_clip(item.get('content'), 900)}"
        for item in latest
        if item.get("content")
    ]
    summary = _clip(" ".join(compact), MAX_SUMMARY_CHARS)
    references: list[str] = []
    for item in messages:
        meta = redact(item.get("meta") or {})
        action_id = meta.get("action_id") if isinstance(meta, dict) else None
        if action_id:
            references.append(f"action_id={action_id}")
    return _normalise({"summary": summary, "facts": compact, "references": references})


def _summarise(messages: list[dict[str, Any]]) -> dict[str, Any]:
    source = json.dumps(redact(messages), ensure_ascii=True, separators=(",", ":"))
    source = source[-MAX_SOURCE_CHARS:]
    completion = azure_client.chat(
        [
            {"role": "system", "content": _memory_system_prompt()},
            {"role": "user", "content": f"Transcript JSON:\n{source}"},
        ],
        temperature=0,
        response_format={"type": "json_object"},
    )
    content = completion.choices[0].message.content or "{}"
    return _normalise(json.loads(content))


def refresh_memory(chat_id: str) -> Optional[dict[str, Any]]:
    """Synchronously refresh memory without allowing summarisation to break chat."""
    chat, messages = _transcript(chat_id)
    if chat is None:
        return None
    previous_data = get_memory(chat_id)
    try:
        data = _summarise(messages) if messages else _normalise({})
    except Exception:
        data = previous_data or _fallback(messages)
    with SessionLocal() as session:
        memory = session.get(ChatMemory, chat_id)
        if memory is None:
            memory = ChatMemory(
                chat_id=chat_id,
                project_id=chat.project_id,
                summary=data["summary"],
                facts=data["facts"],
                references=data["references"],
                unresolved=data["unresolved"],
                requirements=data["requirements"],
                infra_state=data["infra_state"],
                deployment_outcomes=data["deployment_outcomes"],
                source_message_count=len(messages),
                version=1,
            )
            session.add(memory)
        else:
            memory.project_id = chat.project_id
            memory.summary = data["summary"]
            memory.facts = data["facts"]
            memory.references = data["references"]
            memory.unresolved = data["unresolved"]
            memory.requirements = data["requirements"]
            memory.infra_state = data["infra_state"]
            memory.deployment_outcomes = data["deployment_outcomes"]
            memory.source_message_count = len(messages)
            memory.version = (memory.version or 0) + 1
        session.commit()
        return {
            "chat_id": chat_id,
            "project_id": chat.project_id,
            "summary": memory.summary,
            "facts": memory.facts or [],
            "references": memory.references or [],
            "unresolved": memory.unresolved or [],
            "requirements": memory.requirements or [],
            "infra_state": memory.infra_state or {},
            "deployment_outcomes": memory.deployment_outcomes or [],
            "source_message_count": memory.source_message_count,
            "version": memory.version,
        }


def get_requirements(chat_id: str) -> list[str]:
    memory = get_memory(chat_id)
    return _clean_items((memory or {}).get("requirements"))


def record_deployment_outcome(
    chat_id: str,
    *,
    action_id: str,
    status: str,
    summary: str = "",
) -> None:
    """Append a deployment outcome without waiting for full summarisation."""
    memory = get_memory(chat_id)
    if memory is None:
        return
    outcomes = _clean_items(memory.get("deployment_outcomes"))
    line = _clip(
        f"action_id={action_id} status={status}"
        + (f" summary={summary}" if summary else "")
    )
    if line and line not in outcomes:
        outcomes.append(line)
    infra_state = _normalise_infra_state(memory.get("infra_state"))
    if status == "succeeded" and summary:
        deployed = infra_state.get("deployed") or []
        label = _clip(summary, 200)
        if label and label not in deployed:
            deployed.append(label)
            infra_state["deployed"] = deployed[:MAX_ITEMS]
    with SessionLocal() as session:
        row = session.get(ChatMemory, chat_id)
        if row is None:
            return
        row.deployment_outcomes = outcomes[:MAX_ITEMS]
        row.infra_state = infra_state
        row.version = (row.version or 0) + 1
        session.commit()


def rebuild_memory(chat_id: str) -> Optional[dict[str, Any]]:
    return refresh_memory(chat_id)


def delete_memory(chat_id: str) -> None:
    with SessionLocal() as session:
        session.execute(delete(ChatMemory).where(ChatMemory.chat_id == chat_id))
        session.commit()
