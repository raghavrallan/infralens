"""Deterministic stack discovery from inventory, repo files, and the ask."""
from __future__ import annotations

import re
from typing import Any


def _has_token(blob: str, token: str) -> bool:
    return bool(re.search(rf"(?<![a-z0-9]){re.escape(token)}(?![a-z0-9])", blob))


_SIGNAL_TOKENS: tuple[tuple[str, str], ...] = (
    ("next.js", "nextjs"),
    ("nextjs", "nextjs"),
    ("next-env", "nextjs"),
    ('"next":', "nextjs"),
    ("fastapi", "fastapi"),
    ("django", "django"),
    ("flask", "flask"),
    ("express", "node"),
    ("nestjs", "nestjs"),
    ("spring boot", "java"),
    ("postgresql", "postgres"),
    ("postgres", "postgres"),
    ("psycopg", "postgres"),
    ("redis", "redis"),
    ("rq worker", "worker"),
    ("celery", "worker"),
    ("background worker", "worker"),
    ("dockerfile", "docker"),
    ("docker-compose", "docker"),
    ("kubernetes", "kubernetes"),
    ("helm", "helm"),
    ("terraform", "terraform"),
    ("bicep", "bicep"),
    ("github actions", "github_actions"),
    (".github/workflows", "github_actions"),
    ("container app", "aca"),
    ("azure container apps", "aca"),
    ("static web app", "swa"),
    ("key vault", "keyvault"),
    ("aks", "aks"),
    ("eks", "eks"),
    ("lambda", "lambda"),
    ("react", "react"),
    ("requirements.txt", "python"),
    ("package.json", "node"),
    ("go.mod", "go"),
    (".csproj", "dotnet"),
)


def discover(
    *,
    project_id: str,
    inventory: str = "",
    code: str = "",
    objective: str = "",
    seed: str = "",
) -> dict[str, Any]:
    blob = "\n".join([inventory or "", code or "", objective or "", seed or ""]).lower()
    signals = sorted({name for token, name in _SIGNAL_TOKENS if token in blob})
    azure_hit = _has_token(blob, "azure") or "azurerm" in blob or "container app" in blob
    aws_hit = _has_token(blob, "aws") or _has_token(blob, "eks") or "cloudformation" in blob
    gcp_hit = _has_token(blob, "gcp") or _has_token(blob, "gke")
    cloud = "azure"
    if aws_hit and not azure_hit:
        cloud = "aws"
    elif gcp_hit and not azure_hit:
        cloud = "gcp"
    languages: list[str] = []
    for lang in ("python", "node", "go", "java", "dotnet"):
        if lang in signals:
            languages.append(lang)
    if "fastapi" in signals or "django" in signals or "flask" in signals:
        if "python" not in languages:
            languages.append("python")
    if "nextjs" in signals or "react" in signals:
        if "node" not in languages:
            languages.append("node")
    frameworks = [name for name in ("nextjs", "fastapi", "django", "flask", "react", "nestjs") if name in signals]
    return {
        "project_id": project_id,
        "cloud": cloud,
        "signals": signals,
        "languages": languages,
        "frameworks": frameworks,
        "has_code": "github code: not connected" not in (code or "").lower()
        and bool((code or "").strip())
        and "not connected" not in (code or "")[:40].lower(),
        "inventory_empty": "not connected" in (inventory or "").lower()
        and "resource" not in (inventory or "").lower(),
        "evidence_chars": len(blob),
    }
