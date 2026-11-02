"""Deterministic stack discovery from inventory, repo files, connections, and the ask."""
from __future__ import annotations

import re
from typing import Any, Iterable, Optional


def _has_token(blob: str, token: str) -> bool:
    return bool(re.search(rf"(?<![a-z0-9]){re.escape(token)}(?![a-z0-9])", blob))


def _strip_disconnected_provider_blocks(inventory: str) -> str:
    """Drop `azure: not connected` / `aws: not connected` so they do not bias cloud pick."""
    if not inventory:
        return ""
    kept: list[str] = []
    for block in re.split(r"\n{2,}", inventory):
        head = (block.splitlines() or [""])[0].strip().lower()
        if re.match(r"^(azure|aws|gcp|github)\s*:\s*not connected\b", head):
            continue
        if "not connected" in head and head.split(":", 1)[0].strip() in {
            "azure",
            "aws",
            "gcp",
            "github",
        }:
            continue
        kept.append(block)
    return "\n\n".join(kept)


_SIGNAL_TOKENS: tuple[tuple[str, str], ...] = (
    ("next.js", "nextjs"),
    ("nextjs", "nextjs"),
    ("next-env", "nextjs"),
    ('"next":', "nextjs"),
    ("fastapi", "fastapi"),
    ("django", "django"),
    ("flask", "flask"),
    ("express", "express"),
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
    ("ecs", "ecs"),
    ("fargate", "ecs"),
    ("lambda", "lambda"),
    ("rds", "rds"),
    ("dynamodb", "dynamodb"),
    ("s3 bucket", "s3"),
    ("cloudformation", "cloudformation"),
    ("boto3", "boto3"),
    ("react", "react"),
    ("requirements.txt", "python"),
    ("package.json", "node"),
    ("go.mod", "go"),
    (".csproj", "dotnet"),
)

_AZURE_SIGNAL_PATTERNS: tuple[str, ...] = (
    r"\bazurerm\b",
    r"\bazuread\b",
    r"\bazure[-_ ]?cli\b",
    r"\bmicrosoft\.(compute|network|sql|web|keyvault|containerservice)\b",
    r"\bresource[_ ]group\b",
    r"\bcontainer[_ ]?apps?\b",
    r"\bkey[_ ]?vault\b",
    r"\bmanaged[_ ]?identity\b",
    r"\blogs? analytics\b",
    r"\bapp[_ ]?service\b",
    r"\baks\b",
    r"\bbicep\b",
    r"\bazure\b",
)

_AWS_SIGNAL_PATTERNS: tuple[str, ...] = (
    r"\baws[_-]?(vpc|subnet|security_group|lb|alb|nlb|ecs|eks|lambda|rds|s3|iam|ec2|dynamodb|sqs|sns|cloudwatch)\b",
    r'\bprovider\s+"aws"\b',
    r"\bamazon\b",
    r"\bboto3\b",
    r"\bcloudformation\b",
    r"\bcdk\b",
    r"\becs\b",
    r"\bfargate\b",
    r"\beks\b",
    r"\blambda\b",
    r"\brds\b",
    r"\bdynamodb\b",
    r"\bs3://",
    r"\bsecrets[_ ]?manager\b",
    r"\baws\b",
)

_GCP_SIGNAL_PATTERNS: tuple[str, ...] = (
    r"\bgcp\b",
    r"\bgke\b",
    r"\bgoogle_compute\b",
    r'\bprovider\s+"google"\b',
)


def _score_patterns(blob: str, patterns: Iterable[str]) -> int:
    score = 0
    for pattern in patterns:
        matches = re.findall(pattern, blob, flags=re.IGNORECASE)
        if matches:
            score += min(4, len(matches))
    return score


def _normalize_connected(connected: Optional[Iterable[str]]) -> set[str]:
    out: set[str] = set()
    for item in connected or []:
        name = str(item or "").strip().lower()
        if name in {"azure", "aws", "gcp"}:
            out.add(name)
    return out


def resolve_cloud(
    *,
    inventory: str = "",
    code: str = "",
    objective: str = "",
    seed: str = "",
    connected: Optional[Iterable[str]] = None,
) -> tuple[str, dict[str, int]]:
    """Pick the target cloud from connections + evidence. Never invent Azure when only AWS is linked."""
    connected_set = _normalize_connected(connected)
    usable_inventory = _strip_disconnected_provider_blocks(inventory)
    blob = "\n".join([usable_inventory or "", code or "", objective or "", seed or ""]).lower()

    scores = {
        "azure": _score_patterns(blob, _AZURE_SIGNAL_PATTERNS),
        "aws": _score_patterns(blob, _AWS_SIGNAL_PATTERNS),
        "gcp": _score_patterns(blob, _GCP_SIGNAL_PATTERNS),
    }

    # Connected accounts are first-class evidence (docs may be empty).
    for name in connected_set:
        scores[name] = scores.get(name, 0) + 6

    # Live inventory text for a connected cloud is stronger than a vague ask.
    inv = (usable_inventory or "").lower()
    if "azure" in connected_set and re.search(r"\bazure\b", inv):
        scores["azure"] += 3
    if "aws" in connected_set and re.search(r"\baws\b|\bamazon\b", inv):
        scores["aws"] += 3

    ranked = sorted(scores.items(), key=lambda item: item[1], reverse=True)
    best_name, best_score = ranked[0]
    second_score = ranked[1][1] if len(ranked) > 1 else 0

    if best_score <= 0:
        if connected_set == {"aws"}:
            return "aws", scores
        if connected_set == {"azure"}:
            return "azure", scores
        if connected_set == {"gcp"}:
            return "gcp", scores
        if connected_set == {"aws", "azure"}:
            # Both linked, no code/docs signal — stay undecided toward multi-cloud note; prefer AWS only if
            # inventory mentions AWS resources more. Default to azure only when nothing else exists.
            return ("aws" if scores["aws"] >= scores["azure"] else "azure"), scores
        return "azure", scores

    if best_score > second_score:
        # If the winner is not connected but another cloud is, trust the connection when evidence is weak.
        if best_name not in connected_set and connected_set and best_score < 6:
            if len(connected_set) == 1:
                return next(iter(connected_set)), scores
        return best_name, scores

    # Tie: prefer the exclusively connected cloud, else the connected one with inventory, else azure.
    if len(connected_set) == 1:
        return next(iter(connected_set)), scores
    if "aws" in connected_set and scores["aws"] >= scores["azure"]:
        return "aws", scores
    if "azure" in connected_set:
        return "azure", scores
    if "aws" in connected_set:
        return "aws", scores
    return best_name, scores


def discover(
    *,
    project_id: str,
    inventory: str = "",
    code: str = "",
    objective: str = "",
    seed: str = "",
    connected: Optional[Iterable[str]] = None,
) -> dict[str, Any]:
    if connected is None:
        connected = detect_connected_clouds(project_id)

    blob = "\n".join(
        [
            _strip_disconnected_provider_blocks(inventory or ""),
            code or "",
            objective or "",
            seed or "",
        ]
    ).lower()
    signals = sorted({name for token, name in _SIGNAL_TOKENS if token in blob})
    cloud, scores = resolve_cloud(
        inventory=inventory,
        code=code,
        objective=objective,
        seed=seed,
        connected=connected,
    )
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
    connected_list = sorted(_normalize_connected(connected))
    return {
        "project_id": project_id,
        "cloud": cloud,
        "connected_clouds": connected_list,
        "cloud_scores": scores,
        "signals": signals,
        "languages": languages,
        "frameworks": frameworks,
        "has_code": "github code: not connected" not in (code or "").lower()
        and bool((code or "").strip())
        and "not connected" not in (code or "")[:40].lower(),
        "inventory_empty": "not connected" in (inventory or "").lower()
        and "resource" not in (inventory or "").lower(),
        "evidence_chars": len(blob),
        "source_of_truth": (
            "connected_cloud_and_repo"
            if (connected_list or ("github code: not connected" not in (code or "").lower()))
            else "objective_only"
        ),
    }


def detect_connected_clouds(project_id: str) -> list[str]:
    """Return which cloud providers are actually connected for this project."""
    connected: list[str] = []
    try:
        from app.providers import aws_infra, azure_infra
    except Exception:
        return connected
    try:
        if azure_infra.is_connected(project_id):
            connected.append("azure")
    except Exception:
        pass
    try:
        if aws_infra.is_connected(project_id):
            connected.append("aws")
    except Exception:
        pass
    return connected
