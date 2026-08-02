"""Project context engine: fresh vs existing project topology for smart chat.

Builds a structured picture of the project so the orchestrator and skills can
ground every answer in real repos, IaC, and live infrastructure instead of
asking the user to paste files.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from typing import Any, Literal, Optional

from app import connections, projects
from app.providers import aws_infra, azure_infra, github_infra

ProjectMode = Literal["fresh", "existing"]

_MAX_CONTEXT_CHARS = 14000
_TF_KINDS = ("terraform", "tfvars")
_CODE_KINDS = ("terraform", "bicep", "kubernetes", "dockerfile", "workflows", "azure_pipelines", "source")


@dataclass
class ProjectContext:
    """Structured project topology used by chat planning and infra skills."""

    project_id: str
    mode: ProjectMode
    project_name: str = ""
    repos: list[str] = field(default_factory=list)
    providers: dict[str, dict[str, Any]] = field(default_factory=dict)
    iac_files: list[dict[str, str]] = field(default_factory=list)
    app_structure: dict[str, Any] = field(default_factory=dict)
    live_resources: dict[str, Any] = field(default_factory=dict)
    requirements: list[str] = field(default_factory=list)
    gaps: list[str] = field(default_factory=list)
    summary: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def to_prompt_text(self) -> str:
        """Render a bounded, secret-free block for LLM system context."""
        lines = [
            "PROJECT TOPOLOGY (authoritative; use this instead of asking the user to paste files):",
            f"- Project: {self.project_name or self.project_id} ({self.project_id})",
            f"- Mode: {self.mode}",
            f"- Mapped repositories: {', '.join(self.repos) if self.repos else '(none)'}",
        ]
        azure = self.providers.get("azure") or {}
        github = self.providers.get("github") or {}
        if azure.get("connected"):
            lines.append(
                "- Default Azure scope: entire connected subscription "
                "(do not ask subscription vs resource group vs names)."
            )
        if github.get("connected"):
            mapped = ", ".join(self.repos) if self.repos else "all repos visible to the token"
            lines.append(
                f"- Default GitHub scope: {mapped} "
                "(do not ask which repository when one is mapped or named in chat)."
            )
        for name, status in self.providers.items():
            state = "connected" if status.get("connected") else "not connected"
            identity = status.get("identity") or ""
            lines.append(
                f"- Provider {name}: {state}"
                + (f" ({identity})" if identity else "")
            )
        if self.app_structure:
            lines.append(
                "- Application structure: "
                + json.dumps(self.app_structure, ensure_ascii=True)[:2000]
            )
        if self.iac_files:
            lines.append("- IaC / infra files discovered:")
            for item in self.iac_files[:40]:
                repo = item.get("repo", "")
                path = item.get("path", "")
                branch = item.get("branch", "")
                lines.append(f"  - {repo}:{path}@{branch}" if branch else f"  - {repo}:{path}")
        if self.live_resources:
            lines.append(
                "- Live infrastructure summary: "
                + json.dumps(self.live_resources, ensure_ascii=True)[:2500]
            )
        if self.requirements:
            lines.append("- Accumulated requirements:")
            lines.extend(f"  - {item}" for item in self.requirements[:20])
        if self.gaps:
            lines.append("- Gaps / unknowns:")
            lines.extend(f"  - {item}" for item in self.gaps[:16])
        if self.summary:
            lines.append(f"- Summary: {self.summary[:2000]}")
        text = "\n".join(lines)
        return text[:_MAX_CONTEXT_CHARS]


def detect_project_mode(project_id: str) -> ProjectMode:
    """Fresh = no mapped repos and no discovered IaC; otherwise existing."""
    repos = projects.get_repos(project_id)
    if repos:
        return "existing"
    github_ok = github_infra.is_connected(project_id)
    azure_ok = azure_infra.is_connected(project_id)
    aws_ok = aws_infra.is_connected(project_id)
    if github_ok or azure_ok or aws_ok:
        # Connected providers with no repos yet is still mostly a greenfield workspace.
        return "fresh" if not repos else "existing"
    return "fresh"


def _provider_status(project_id: str) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for item in connections.all_status(project_id):
        result[str(item.get("provider"))] = {
            "connected": bool(item.get("connected")),
            "identity": item.get("identity") or "",
        }
    return result


def _extract_iac_inventory(project_id: str) -> list[dict[str, str]]:
    if not github_infra.is_connected(project_id):
        return []
    try:
        report = github_infra.build_code_report(
            project_id,
            list(_TF_KINDS) + ["bicep", "kubernetes", "dockerfile", "workflows", "azure_pipelines"],
            max_files=24,
            max_per_repo=8,
            max_bytes=4000,
            max_repos=12,
        )
    except (github_infra.GitHubConnectionError, github_infra.GitHubApiError):
        return []
    if not report:
        return []
    meta = report.get("meta") or {}
    # Prefer structured file list when present; otherwise parse from text headers.
    files: list[dict[str, str]] = []
    text = str(report.get("text") or "")
    for line in text.splitlines():
        if line.startswith("### ") and " — " in line:
            # ### owner/repo — path (branch: name)
            body = line[4:]
            repo_part, _, rest = body.partition(" — ")
            path_part, _, branch_part = rest.partition(" (branch: ")
            branch = branch_part.rstrip(")") if branch_part else ""
            files.append(
                {
                    "repo": repo_part.strip(),
                    "path": path_part.strip(),
                    "branch": branch,
                    "kind": _kind_for_path(path_part.strip()),
                }
            )
    if not files and meta.get("files"):
        files.append({"repo": "", "path": f"{meta.get('files')} matching files", "branch": "", "kind": "mixed"})
    return files


def _kind_for_path(path: str) -> str:
    lowered = path.lower()
    if lowered.endswith(".tf") or lowered.endswith(".tfvars") or "terraform" in lowered:
        return "terraform"
    if lowered.endswith(".bicep"):
        return "bicep"
    if "dockerfile" in lowered:
        return "dockerfile"
    if "/.github/workflows/" in lowered or lowered.endswith(".yml") or lowered.endswith(".yaml"):
        return "pipeline"
    if "helm" in lowered or "/k8s/" in lowered or "/kubernetes/" in lowered:
        return "kubernetes"
    return "other"


def _infer_app_structure(iac_files: list[dict[str, str]], repos: list[str]) -> dict[str, Any]:
    has_tf = any(item.get("kind") == "terraform" for item in iac_files)
    has_bicep = any(item.get("kind") == "bicep" for item in iac_files)
    has_k8s = any(item.get("kind") == "kubernetes" for item in iac_files)
    has_pipeline = any(item.get("kind") == "pipeline" for item in iac_files)
    be_hints = [r for r in repos if any(token in r.lower() for token in ("api", "backend", "be", "service"))]
    fe_hints = [r for r in repos if any(token in r.lower() for token in ("web", "frontend", "fe", "ui", "app"))]
    infra_hints = [r for r in repos if any(token in r.lower() for token in ("infra", "iac", "terraform", "platform"))]
    return {
        "has_terraform": has_tf,
        "has_bicep": has_bicep,
        "has_kubernetes": has_k8s,
        "has_pipelines": has_pipeline,
        "backend_repos": be_hints,
        "frontend_repos": fe_hints,
        "infra_repos": infra_hints or [r for r in repos if has_tf],
        "repo_count": len(repos),
        "iac_file_count": len(iac_files),
    }


def _live_resource_summary(project_id: str) -> dict[str, Any]:
    summary: dict[str, Any] = {}
    if azure_infra.is_connected(project_id):
        try:
            if hasattr(azure_infra, "discover_topology"):
                topo = azure_infra.discover_topology(project_id, max_resources=80)
                summary["azure"] = {
                    "subscription": topo.get("subscription"),
                    "resource_count": topo.get("resource_count"),
                    "resource_groups": topo.get("resource_groups"),
                    "relationship_count": len(topo.get("relationships") or []),
                }
            else:
                report = azure_infra.build_environment_report(project_id, max_resources=80)
                meta = report.get("meta") or {}
                summary["azure"] = {
                    "subscription": meta.get("subscription"),
                    "resource_count": meta.get("resource_count"),
                    "type_count": meta.get("type_count"),
                }
        except (azure_infra.AzureConnectionError, azure_infra.AzureApiError) as exc:
            summary["azure"] = {"error": str(exc)[:300]}
    if aws_infra.is_connected(project_id):
        try:
            if hasattr(aws_infra, "discover_topology"):
                topo = aws_infra.discover_topology(project_id)
                summary["aws"] = {
                    "account": topo.get("account"),
                    "region": topo.get("region"),
                    "resource_count": topo.get("resource_count"),
                    "relationship_count": len(topo.get("relationships") or []),
                }
            else:
                report = aws_infra.build_environment_report(project_id)
                meta = report.get("meta") or {}
                summary["aws"] = {
                    key: meta.get(key)
                    for key in ("account", "region", "resource_count")
                    if key in meta
                }
                if not summary["aws"]:
                    summary["aws"] = {"connected": True}
        except (aws_infra.AwsConnectionError, aws_infra.AwsApiError) as exc:
            summary["aws"] = {"error": str(exc)[:300]}
    if github_infra.is_connected(project_id):
        try:
            report = github_infra.build_environment_report(project_id)
            meta = report.get("meta") or {}
            summary["github"] = {
                key: meta.get(key)
                for key in ("repos", "org", "login", "scope")
                if key in meta
            } or {"connected": True}
        except (github_infra.GitHubConnectionError, github_infra.GitHubApiError) as exc:
            summary["github"] = {"error": str(exc)[:300]}
    return summary


def build_fresh_context(
    project_id: str,
    user_messages: Optional[list[str]] = None,
    docs: Optional[str] = None,
    requirements: Optional[list[str]] = None,
) -> ProjectContext:
    """Build context for a greenfield project from chat requirements and docs."""
    project = projects.get_project(project_id) or {}
    reqs = list(requirements or [])
    for message in user_messages or []:
        text = " ".join(str(message or "").split())
        if text and text not in reqs:
            reqs.append(text[:500])
    if docs:
        reqs.append(f"Documented requirements: {docs[:1500]}")
    gaps: list[str] = []
    providers = _provider_status(project_id)
    if not providers.get("azure", {}).get("connected") and not providers.get("aws", {}).get("connected"):
        gaps.append("No cloud provider connected; connect Azure or AWS in Settings before provisioning.")
    if not providers.get("github", {}).get("connected"):
        gaps.append("GitHub is not connected; connect it to store generated Terraform in a repository.")
    if not reqs:
        gaps.append("No requirements captured yet; ask the user what to build (regions, workloads, networking).")
    summary = (
        "Fresh project workspace. Design infrastructure from user requirements, "
        "generate Terraform, and provision through the approved CLI/TF path."
    )
    return ProjectContext(
        project_id=project_id,
        mode="fresh",
        project_name=str(project.get("name") or ""),
        repos=list(project.get("repos") or []),
        providers=providers,
        requirements=reqs[:30],
        gaps=gaps,
        summary=summary,
    )


def build_existing_context(
    project_id: str,
    requirements: Optional[list[str]] = None,
) -> ProjectContext:
    """Build context for an existing project from repos + live infra."""
    project = projects.get_project(project_id) or {}
    repos = list(project.get("repos") or projects.get_repos(project_id))
    providers = _provider_status(project_id)
    iac_files = _extract_iac_inventory(project_id)
    app_structure = _infer_app_structure(iac_files, repos)
    live_resources = _live_resource_summary(project_id)
    gaps: list[str] = []
    if not repos:
        gaps.append("No repositories mapped to this project.")
    if not iac_files and providers.get("github", {}).get("connected"):
        gaps.append("No Terraform/Bicep/K8s/pipeline files discovered in mapped repositories.")
    if not live_resources:
        gaps.append("No live cloud inventory available; connect Azure/AWS or grant Reader access.")
    summary = (
        f"Existing project with {len(repos)} mapped repo(s), "
        f"{len(iac_files)} discovered IaC/pipeline file(s), and "
        f"{len(live_resources)} live provider inventory source(s)."
    )
    return ProjectContext(
        project_id=project_id,
        mode="existing",
        project_name=str(project.get("name") or ""),
        repos=repos,
        providers=providers,
        iac_files=iac_files,
        app_structure=app_structure,
        live_resources=live_resources,
        requirements=list(requirements or [])[:30],
        gaps=gaps,
        summary=summary,
    )


def build_project_context(
    project_id: str,
    *,
    user_messages: Optional[list[str]] = None,
    docs: Optional[str] = None,
    requirements: Optional[list[str]] = None,
    force_mode: Optional[ProjectMode] = None,
) -> ProjectContext:
    """Detect mode and build the appropriate project context."""
    mode = force_mode or detect_project_mode(project_id)
    if mode == "fresh":
        return build_fresh_context(
            project_id,
            user_messages=user_messages,
            docs=docs,
            requirements=requirements,
        )
    return build_existing_context(project_id, requirements=requirements)


def gather_project_topology(
    project_id: str,
    *,
    user_messages: Optional[list[str]] = None,
    requirements: Optional[list[str]] = None,
) -> str:
    """Convenience helper returning prompt-ready topology text."""
    try:
        ctx = build_project_context(
            project_id,
            user_messages=user_messages,
            requirements=requirements,
        )
        return ctx.to_prompt_text()
    except Exception as exc:  # noqa: BLE001 - never break chat for topology failures
        return (
            "PROJECT TOPOLOGY unavailable. Proceed carefully and ask only for "
            f"missing values that cannot be discovered. Error: {exc}"
        )
