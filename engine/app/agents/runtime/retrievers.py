"""LangChain-style retrievers over InfraLens engineering memory (Postgres truth)."""
from __future__ import annotations

from typing import Any, Optional

from app.platform import memory as eng_memory


class PrecedentRetriever:
    """Thin retriever adapter — does not replace EngineeringMemory tables."""

    def __init__(self, project_id: str, *, limit: int = 8) -> None:
        self.project_id = project_id
        self.limit = limit

    def invoke(
        self,
        query: str = "",
        *,
        skill: Optional[str] = None,
        module: Optional[str] = None,
        resource: Optional[str] = None,
    ) -> list[dict[str, Any]]:
        rows = eng_memory.list_precedent(
            self.project_id,
            skill=skill,
            module=module,
            resource=resource or (query or None),
            limit=self.limit,
        )
        return rows

    def as_text(self, **kwargs: Any) -> str:
        rows = self.invoke(**kwargs) if kwargs else self.invoke()
        if not rows:
            return "No engineering precedent recorded."
        lines = []
        for row in rows:
            lines.append(
                f"- [{row.get('outcome') or 'unknown'}] {row.get('summary') or row.get('kind')}"
            )
        return "\n".join(lines)


def get_precedent_retriever(project_id: str, *, limit: int = 8) -> PrecedentRetriever:
    return PrecedentRetriever(project_id, limit=limit)
