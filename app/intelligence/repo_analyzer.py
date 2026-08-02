"""Deep repository analysis for existing projects (BE/FE/IaC/CI)."""
from __future__ import annotations

import re
from typing import Any, Optional

from app import projects
from app.providers import github_infra
from app.project_context import build_existing_context

_BE_MARKERS = (
    "requirements.txt",
    "pyproject.toml",
    "go.mod",
    "pom.xml",
    "build.gradle",
    "package.json",
    "Cargo.toml",
    "Gemfile",
    "composer.json",
)
_FE_MARKERS = (
    "package.json",
    "next.config",
    "vite.config",
    "angular.json",
    "nuxt.config",
)
_INFRA_MARKERS = (".tf", ".tfvars", ".bicep", "helm/", "kustomization", "Dockerfile")
_PIPELINE_MARKERS = (".github/workflows/", "azure-pipelines", ".gitlab-ci", "Jenkinsfile")


def _classify_path(path: str) -> list[str]:
    lowered = path.lower().replace("\\", "/")
    tags: list[str] = []
    if any(marker in lowered for marker in _INFRA_MARKERS) or lowered.endswith(".tf"):
        tags.append("iac")
    if any(marker in lowered for marker in _PIPELINE_MARKERS):
        tags.append("pipeline")
    if any(lowered.endswith(marker) or f"/{marker}" in lowered for marker in _BE_MARKERS):
        tags.append("backend")
    if any(marker in lowered for marker in _FE_MARKERS):
        tags.append("frontend")
    if "dockerfile" in lowered:
        tags.append("container")
    return tags or ["other"]


def _framework_hint(path: str, content_sample: str = "") -> str:
    blob = f"{path}\n{content_sample}".lower()
    if "fastapi" in blob or "uvicorn" in blob:
        return "fastapi"
    if "django" in blob:
        return "django"
    if "flask" in blob:
        return "flask"
    if "next" in blob:
        return "nextjs"
    if "react" in blob:
        return "react"
    if "spring" in blob:
        return "spring"
    if "express" in blob:
        return "express"
    if "terraform" in blob or path.endswith(".tf"):
        return "terraform"
    return ""


def analyze_repositories(project_id: str) -> dict[str, Any]:
    """Scan mapped repos and return structure, dependency hints, and env branches."""
    context = build_existing_context(project_id)
    repos = context.repos or projects.get_repos(project_id)
    if not github_infra.is_connected(project_id):
        return {
            "project_id": project_id,
            "mode": "existing",
            "repos": repos,
            "error": "GitHub is not connected",
            "topology": context.to_dict(),
        }

    try:
        report = github_infra.build_code_report(
            project_id,
            [
                "terraform",
                "bicep",
                "kubernetes",
                "dockerfile",
                "workflows",
                "azure_pipelines",
                "source",
            ],
            max_files=30,
            max_per_repo=10,
            max_bytes=5000,
            max_repos=15,
        )
    except (github_infra.GitHubConnectionError, github_infra.GitHubApiError) as exc:
        return {
            "project_id": project_id,
            "mode": "existing",
            "repos": repos,
            "error": str(exc)[:400],
            "topology": context.to_dict(),
        }

    files: list[dict[str, Any]] = []
    text = str((report or {}).get("text") or "")
    current: dict[str, Any] = {}
    for line in text.splitlines():
        if line.startswith("### ") and " — " in line:
            if current:
                files.append(current)
            body = line[4:]
            repo_part, _, rest = body.partition(" — ")
            path_part, _, branch_part = rest.partition(" (branch: ")
            current = {
                "repo": repo_part.strip(),
                "path": path_part.strip(),
                "branch": branch_part.rstrip(")"),
                "tags": _classify_path(path_part.strip()),
                "framework": "",
                "content_preview": "",
            }
        elif current and line.startswith("```"):
            continue
        elif current and not line.startswith("```"):
            if len(current["content_preview"]) < 400:
                current["content_preview"] += line + "\n"
    if current:
        files.append(current)

    for item in files:
        item["framework"] = _framework_hint(item.get("path", ""), item.get("content_preview", ""))

    by_repo: dict[str, dict[str, Any]] = {}
    for item in files:
        repo = item.get("repo") or "unknown"
        entry = by_repo.setdefault(
            repo,
            {
                "repo": repo,
                "roles": set(),
                "frameworks": set(),
                "branches": set(),
                "files": [],
            },
        )
        entry["roles"].update(item.get("tags") or [])
        if item.get("framework"):
            entry["frameworks"].add(item["framework"])
        if item.get("branch"):
            entry["branches"].add(item["branch"])
        entry["files"].append(
            {
                "path": item.get("path"),
                "tags": item.get("tags"),
                "framework": item.get("framework"),
                "branch": item.get("branch"),
            }
        )

    repo_summaries = []
    for entry in by_repo.values():
        repo_summaries.append(
            {
                "repo": entry["repo"],
                "roles": sorted(entry["roles"]),
                "frameworks": sorted(entry["frameworks"]),
                "branches": sorted(entry["branches"]),
                "file_count": len(entry["files"]),
                "files": entry["files"][:40],
            }
        )

    env_branches = sorted(
        {
            branch
            for summary in repo_summaries
            for branch in summary.get("branches") or []
            if re.search(r"(dev|develop|staging|stage|uat|qa|prod|production|main|master)", branch, re.I)
        }
    )

    dependency_graph = []
    infra_repos = [r["repo"] for r in repo_summaries if "iac" in r["roles"]]
    app_repos = [r["repo"] for r in repo_summaries if "backend" in r["roles"] or "frontend" in r["roles"]]
    for app in app_repos:
        for infra in infra_repos or ["(inline IaC)"]:
            dependency_graph.append({"from": app, "to": infra, "relation": "deployed_by"})

    return {
        "project_id": project_id,
        "mode": "existing",
        "repos": repos,
        "repository_summaries": repo_summaries,
        "environment_branches": env_branches,
        "dependency_graph": dependency_graph,
        "iac_files": context.iac_files,
        "app_structure": context.app_structure,
        "live_resources": context.live_resources,
        "gaps": context.gaps,
        "summary": context.summary,
    }


def analyze_to_prompt(project_id: str) -> str:
    data = analyze_repositories(project_id)
    lines = [
        "REPOSITORY ANALYSIS:",
        f"- Project: {project_id}",
        f"- Repos: {', '.join(data.get('repos') or []) or '(none)'}",
        f"- Environment branches: {', '.join(data.get('environment_branches') or []) or '(none detected)'}",
    ]
    for summary in data.get("repository_summaries") or []:
        lines.append(
            f"- {summary['repo']}: roles={','.join(summary.get('roles') or [])}; "
            f"frameworks={','.join(summary.get('frameworks') or [])}; "
            f"files={summary.get('file_count')}"
        )
    for edge in (data.get("dependency_graph") or [])[:20]:
        lines.append(f"- dep: {edge.get('from')} -> {edge.get('to')} ({edge.get('relation')})")
    for gap in data.get("gaps") or []:
        lines.append(f"- gap: {gap}")
    if data.get("error"):
        lines.append(f"- error: {data['error']}")
    return "\n".join(lines)[:12000]
