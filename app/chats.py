"""Chat persistence: create chats, append messages, list and load history.

Every conversation is stored in Postgres with a UUID so the UI can list past
chats and switch between them.
"""
import uuid
from typing import Any, Optional

from sqlalchemy import delete, select

from app.db import DEFAULT_PROJECT_ID, Chat, Message, SessionLocal


def _title_from_text(text: str) -> str:
    cleaned = " ".join(text.strip().split())
    if len(cleaned) <= 60:
        return cleaned or "New chat"
    return cleaned[:57].rstrip() + "…"


def create_chat(
    first_message: Optional[str] = None, project_id: str = DEFAULT_PROJECT_ID
) -> dict[str, Any]:
    chat_id = str(uuid.uuid4())
    title = _title_from_text(first_message) if first_message else "New chat"
    with SessionLocal() as session:
        chat = Chat(id=chat_id, project_id=project_id, title=title)
        session.add(chat)
        session.commit()
        return _chat_summary(chat)


def _chat_summary(chat: Chat) -> dict[str, Any]:
    return {
        "id": chat.id,
        "project_id": chat.project_id,
        "title": chat.title,
        "created_at": chat.created_at.isoformat() if chat.created_at else None,
        "updated_at": chat.updated_at.isoformat() if chat.updated_at else None,
    }


def list_chats(project_id: Optional[str] = None) -> list[dict[str, Any]]:
    with SessionLocal() as session:
        query = select(Chat).order_by(Chat.updated_at.desc())
        if project_id is not None:
            query = query.where(Chat.project_id == project_id)
        rows = session.execute(query).scalars()
        return [_chat_summary(c) for c in rows]


def get_chat(chat_id: str) -> Optional[dict[str, Any]]:
    with SessionLocal() as session:
        chat = session.get(Chat, chat_id)
        if chat is None:
            return None
        rows = session.execute(
            select(Message)
            .where(Message.chat_id == chat_id)
            .order_by(Message.created_at.asc(), Message.id.asc())
        ).scalars()
        messages = [
            {
                "id": m.id,
                "role": m.role,
                "content": m.content,
                "meta": m.meta or {},
            }
            for m in rows
        ]
        summary = _chat_summary(chat)
        summary["messages"] = messages
        return summary


def get_history(chat_id: str) -> list[dict[str, str]]:
    """Return prior messages as role/content dicts for LLM context."""
    with SessionLocal() as session:
        rows = session.execute(
            select(Message)
            .where(Message.chat_id == chat_id)
            .order_by(Message.created_at.asc(), Message.id.asc())
        ).scalars()
        return [{"role": m.role, "content": m.content} for m in rows]


def add_message(
    chat_id: str,
    role: str,
    content: str,
    meta: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    with SessionLocal() as session:
        message = Message(
            id=str(uuid.uuid4()),
            chat_id=chat_id,
            role=role,
            content=content,
            meta=meta or {},
        )
        session.add(message)
        chat = session.get(Chat, chat_id)
        if chat is not None and chat.title == "New chat" and role == "user":
            chat.title = _title_from_text(content)
        session.commit()
        return {"id": message.id, "role": role, "content": content, "meta": meta or {}}


def replace_user_message(chat_id: str, message_id: str, content: str) -> bool:
    """Edit a user turn and discard the stale assistant context after it."""
    with SessionLocal() as session:
        target = session.get(Message, message_id)
        if target is None or target.chat_id != chat_id or target.role != "user":
            return False
        rows = list(
            session.execute(
                select(Message)
                .where(Message.chat_id == chat_id)
                .order_by(Message.created_at.asc(), Message.id.asc())
            ).scalars()
        )
        try:
            target_index = next(index for index, row in enumerate(rows) if row.id == message_id)
        except StopIteration:
            return False
        for stale in rows[target_index + 1 :]:
            session.delete(stale)
        target.content = content
        session.commit()
        # Rebuild immediately so the edited turn cannot leave stale facts in
        # the compact context used by the next request.
        from app import chat_memory

        chat_memory.rebuild_memory(chat_id)
        return True


def rename_chat(chat_id: str, title: str) -> Optional[dict[str, Any]]:
    with SessionLocal() as session:
        chat = session.get(Chat, chat_id)
        if chat is None:
            return None
        chat.title = _title_from_text(title)
        session.commit()
        return _chat_summary(chat)


def delete_chat(chat_id: str) -> bool:
    with SessionLocal() as session:
        chat = session.get(Chat, chat_id)
        if chat is None:
            return False
        session.execute(delete(Message).where(Message.chat_id == chat_id))
        session.delete(chat)
        session.commit()
        from app import chat_memory

        chat_memory.delete_memory(chat_id)
        return True
