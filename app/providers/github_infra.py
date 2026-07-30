"""Live GitHub connector.

Uses the GitHub connection stored in Settings (personal access token, and
optional username / organisation) to call the GitHub REST API and build a
compact, security-focused report of the user's repositories: visibility,
branch protection, vulnerability alerts and Actions posture. Skills reason over
this REAL data, so "review my GitHub" analyses the actual org/account instead of
asking the user to paste files.

Everything here is READ-ONLY: it only issues GET requests; it never creates,
updates or deletes anything.
"""
import json
import re
from dataclasses import dataclass
from typing import Any, Optional

import httpx

from app import connections, projects

# Common short aliases users type for a repo/project role.
_REPO_ALIASES = {
    "be": ("backend", "back-end", "server", "api"),
    "backend": ("backend", "back-end", "server", "api"),
    "fe": ("frontend", "front-end", "web", "ui", "client"),
    "frontend": ("frontend", "front-end", "web", "ui", "client"),
    "infra": ("infra", "infrastructure", "terraform", "iac"),
    "iac": ("iac", "infra", "infrastructure", "terraform"),
}

_API = "https://api.github.com"
_TIMEOUT = 30.0
_HEADERS = {
    "Accept": "application/vnd.github+json",
    "X-GitHub-Api-Version": "2022-11-28",
}
# Keep per-repo probes bounded so a big org doesn't stall the chat.
_MAX_REPOS = 40
_PROBE_REPOS = 12


class GitHubConnectionError(RuntimeError):
    """Raised when GitHub is not connected or credentials are incomplete."""


class GitHubApiError(RuntimeError):
    """Raised when a GitHub API call fails (auth, permissions, throttling…)."""


@dataclass
class GitHubCredentials:
    token: str
    username: Optional[str] = None
    org: Optional[str] = None


def load_credentials(project_id: str) -> GitHubCredentials:
    fields = connections.get_secret_fields(project_id, "github")
    if not fields:
        raise GitHubConnectionError("No GitHub connection is configured for this project.")
    token = fields.get("token") or ""
    if not token:
        raise GitHubConnectionError(
            "GitHub connection is missing a personal access token."
        )
    return GitHubCredentials(
        token=token,
        username=fields.get("username") or None,
        org=fields.get("org") or None,
    )


def is_connected(project_id: str) -> bool:
    try:
        load_credentials(project_id)
        return True
    except GitHubConnectionError:
        return False


def _allowed_repos(project_id: str) -> Optional[set[str]]:
    """Repos this project may inspect, or None when it should see all of them."""
    mapped = {r.lower() for r in projects.get_repos(project_id)}
    return mapped or None


def _filter_repos(
    repos: list[dict[str, Any]], allowed: Optional[set[str]]
) -> list[dict[str, Any]]:
    if not allowed:
        return repos
    return [r for r in repos if (r.get("full_name") or "").lower() in allowed]


def list_repo_names(project_id: str) -> list[str]:
    """Return every repository full name the project's token can see (for mapping)."""
    creds = load_credentials(project_id)
    with _client(creds) as client:
        who = _get(client, "/user")
        if who.status_code in (401, 403):
            raise GitHubApiError(
                f"GitHub token rejected ({who.status_code}): {_error_detail(who)}."
            )
        repos = _list_repos(client, creds)
    return sorted({r.get("full_name") for r in repos if r.get("full_name")})


def _error_detail(resp: httpx.Response) -> str:
    try:
        body = resp.json()
    except (ValueError, json.JSONDecodeError):
        return resp.text[:300]
    if isinstance(body, dict) and body.get("message"):
        return str(body["message"])[:300]
    return json.dumps(body)[:300]


def _client(creds: GitHubCredentials) -> httpx.Client:
    headers = {**_HEADERS, "Authorization": f"Bearer {creds.token}"}
    return httpx.Client(base_url=_API, headers=headers, timeout=_TIMEOUT)


def _get(client: httpx.Client, path: str, params: Optional[dict[str, Any]] = None) -> httpx.Response:
    try:
        return client.get(path, params=params)
    except httpx.HTTPError as exc:
        raise GitHubApiError(f"GitHub request failed: {exc}") from exc


def _list_repos(
    client: httpx.Client, creds: GitHubCredentials, max_pages: int = 8
) -> list[dict[str, Any]]:
    """List every repository the token can access — personal plus all orgs.

    Uses the full affiliation set so repositories from any organisation the user
    belongs to (or collaborates on) are returned, paginated up to max_pages.
    """
    repos: list[dict[str, Any]] = []
    seen: set[str] = set()
    page = 1
    while page <= max_pages:
        resp = _get(
            client,
            "/user/repos",
            {
                "per_page": 100,
                "page": page,
                "sort": "pushed",
                "affiliation": "owner,collaborator,organization_member",
            },
        )
        if resp.status_code != 200:
            if page == 1:
                raise GitHubApiError(
                    f"Could not list repositories ({resp.status_code}): {_error_detail(resp)}"
                )
            break
        batch = resp.json()
        if not isinstance(batch, list) or not batch:
            break
        for repo in batch:
            full_name = repo.get("full_name")
            if full_name and full_name not in seen:
                seen.add(full_name)
                repos.append(repo)
        if len(batch) < 100:
            break
        page += 1
    return repos


def _branch_protection(client: httpx.Client, full_name: str, branch: str) -> str:
    resp = _get(client, f"/repos/{full_name}/branches/{branch}/protection")
    if resp.status_code == 200:
        return "protected"
    if resp.status_code == 404:
        return "not protected"
    if resp.status_code in (401, 403):
        return "unknown (token lacks admin scope)"
    return f"unknown ({resp.status_code})"


def _vuln_alerts(client: httpx.Client, full_name: str) -> str:
    resp = _get(client, f"/repos/{full_name}/vulnerability-alerts")
    if resp.status_code == 204:
        return "enabled"
    if resp.status_code == 404:
        return "disabled"
    if resp.status_code in (401, 403):
        return "unknown (token lacks scope)"
    return f"unknown ({resp.status_code})"


def _dependabot_alerts(client: httpx.Client, full_name: str) -> dict[str, Any]:
    """Return bounded Dependabot alert evidence without failing the whole report."""
    resp = _get(
        client,
        f"/repos/{full_name}/dependabot/alerts",
        {"per_page": 50, "state": "open"},
    )
    if resp.status_code == 200:
        rows = resp.json()
        alerts = []
        for row in rows if isinstance(rows, list) else []:
            dependency = row.get("dependency") or {}
            advisory = row.get("security_advisory") or {}
            alerts.append(
                {
                    "state": row.get("state"),
                    "severity": advisory.get("severity") or row.get("severity"),
                    "cve": advisory.get("cve_id"),
                    "ghsa": advisory.get("ghsa_url"),
                    "package": (dependency.get("package") or {}).get("name"),
                    "ecosystem": (dependency.get("package") or {}).get("ecosystem"),
                    "manifest": dependency.get("manifest_path"),
                    "vulnerableVersion": (dependency.get("vulnerable_version_range")),
                    "patchedVersion": (
                        (row.get("security_vulnerability") or {}).get(
                            "first_patched_version"
                        )
                        or {}
                    ).get("identifier"),
                }
            )
        return {"status": "available", "alerts": alerts[:50]}
    if resp.status_code in (403, 404):
        return {"status": "unavailable", "reason": _error_detail(resp)}
    return {"status": f"error ({resp.status_code})", "reason": _error_detail(resp)}


# Artifact kinds the suite can locate and fetch from the user's repositories.
# A path matches when it satisfies the suffix rule AND (if present) the path rule.
_CODE_MATCHERS: dict[str, dict[str, Any]] = {
    "terraform": {"label": "Terraform", "lang": "hcl", "suffixes": (".tf", ".tfvars")},
    "bicep": {"label": "Bicep", "lang": "bicep", "suffixes": (".bicep",)},
    "dockerfile": {"label": "Dockerfile", "lang": "dockerfile", "names": ("dockerfile",)},
    "kubernetes": {
        "label": "Kubernetes manifest",
        "lang": "yaml",
        "suffixes": (".yaml", ".yml"),
        "path_any": ("k8s", "kubernetes", "manifest", "helm", "chart", "deploy"),
    },
    "workflows": {
        "label": "GitHub Actions workflow",
        "lang": "yaml",
        "suffixes": (".yml", ".yaml"),
        "path_any": (".github/workflows",),
    },
    "azure_pipelines": {
        "label": "Azure DevOps pipeline",
        "lang": "yaml",
        "suffixes": (".yml", ".yaml"),
        "path_any": (
            "azure-pipelines",
            "azure/",
            "/pipelines/",
            "pipelines/",
            "/templates/",
            "pipeline",
            ".ado",
        ),
    },
    "ansible": {
        "label": "Ansible",
        "lang": "yaml",
        "suffixes": (".yml", ".yaml"),
        "path_any": ("ansible", "playbook", "roles"),
    },
    "security": {
        "label": "security and dependency evidence",
        "lang": "",
        "names": (
            "package.json", "package-lock.json", "npm-shrinkwrap.json", "yarn.lock",
            "pnpm-lock.yaml", "requirements.txt", "requirements-dev.txt", "pipfile",
            "pipfile.lock", "poetry.lock", "pyproject.toml", "go.mod", "go.sum",
            "pom.xml", "build.gradle", "build.gradle.kts", "packages.config",
            "packages.lock.json", "cargo.toml", "cargo.lock", "composer.json",
            "composer.lock", "gemfile", "gemfile.lock", "mix.exs", "mix.lock",
        ),
        "suffixes": (".sarif", ".json", ".xml", ".yaml", ".yml", ".txt"),
        "path_any": (
            "security", "scanner", "scan", "trivy", "snyk", "grype", "codeql",
            "dependabot", "sbom", "sca", "vulnerability",
        ),
    },
    "source": {
        "label": "application source",
        "lang": "",
        "suffixes": (
            ".py", ".ts", ".tsx", ".js", ".jsx", ".go", ".java", ".cs", ".rb",
            ".rs", ".php", ".kt",
        ),
    },
}
# File extension -> code-fence language for display.
_LANG_BY_EXT = {
    "py": "python", "ts": "typescript", "tsx": "tsx", "js": "javascript",
    "jsx": "jsx", "go": "go", "java": "java", "cs": "csharp", "rb": "ruby",
    "rs": "rust", "php": "php", "kt": "kotlin", "yml": "yaml", "yaml": "yaml",
    "tf": "hcl", "tfvars": "hcl", "bicep": "bicep",
}
# Path fragments that make a source file a likely entry point worth reading first.
_SOURCE_PRIORITY = (
    "main.", "app.", "index.", "server.", "settings.", "config.", "startup.",
    "program.", "__init__.", "manage.", "wsgi.", "asgi.",
)
# Noise to skip when reading application source.
_SOURCE_SKIP = (
    "test", "spec", "mock", "fixture", "node_modules", "dist/", "build/",
    "vendor/", ".min.", "migrations/", "__snapshots__",
)
# Language hints that make a repo a good candidate for a given artifact kind.
_PRIORITY_LANGS = {"hcl", "dockerfile", "yaml", "shell", "hcl2"}


def _lang_for(path: str, fallback: str) -> str:
    if fallback:
        return fallback
    ext = path.rsplit(".", 1)[-1].lower() if "." in path else ""
    return _LANG_BY_EXT.get(ext, "")


def _path_matches(path: str, matcher: dict[str, Any]) -> bool:
    p = path.lower()
    if "names" in matcher and p.rsplit("/", 1)[-1] in matcher["names"]:
        return True
    if "suffixes" in matcher and not any(p.endswith(s) for s in matcher["suffixes"]):
        return False
    if "path_any" in matcher and not any(sub in p for sub in matcher["path_any"]):
        return False
    return "suffixes" in matcher or "path_any" in matcher


# Environment keyword -> candidate branch names, in priority order.
_ENV_BRANCHES: dict[str, tuple[str, ...]] = {
    "dev": ("develop", "development", "dev"),
    "uat": ("uat",),
    "qa": ("qa",),
    "staging": ("staging", "stage", "stg"),
    "preprod": ("preprod", "pre-prod", "preproduction"),
    "prod": ("main", "master", "production", "prod", "release"),
}
# When no env is stated, prefer the active integration branch if it exists.
_ACTIVE_BRANCHES = ("develop", "development")


def _list_branches(client: httpx.Client, full_name: str) -> list[str]:
    names: list[str] = []
    page = 1
    while page <= 3:
        resp = _get(client, f"/repos/{full_name}/branches", {"per_page": 100, "page": page})
        if resp.status_code != 200:
            break
        batch = resp.json()
        if not isinstance(batch, list) or not batch:
            break
        names.extend(b.get("name") for b in batch if b.get("name"))
        if len(batch) < 100:
            break
        page += 1
    return names


def _resolve_branch(
    branches: list[str],
    default_branch: str,
    env: Optional[str] = None,
    explicit: Optional[str] = None,
) -> str:
    """Pick the branch to read: explicit name > env-matched > active > default.

    Handles per-repo naming differences (develop vs development) and ignores
    long feature/fix branches when matching an environment.
    """
    lower = {b.lower(): b for b in branches}
    top = [b for b in branches if "/" not in b]

    if explicit:
        if explicit in branches:
            return explicit
        if explicit.lower() in lower:
            return lower[explicit.lower()]
        hit = next((b for b in branches if explicit.lower() in b.lower()), None)
        if hit:
            return hit

    if env and env in _ENV_BRANCHES:
        cands = _ENV_BRANCHES[env]
        for cand in cands:
            if cand in lower and "/" not in lower[cand]:
                return lower[cand]
        for branch in sorted(top, key=len):
            bl = branch.lower()
            if any(bl == c or bl.startswith(c) for c in cands):
                return branch
        for branch in sorted(top, key=len):
            if any(c in branch.lower() for c in cands):
                return branch
    elif env is None:
        for cand in _ACTIVE_BRANCHES:
            if cand in lower and "/" not in lower[cand]:
                return lower[cand]

    return default_branch or "main"


def _candidate_priority(item: tuple[str, dict[str, Any]]) -> tuple[int, int, str]:
    """Sort matched files so entry points and shallow paths are read first."""
    path, matcher = item
    lower = path.lower()
    name = lower.rsplit("/", 1)[-1]
    is_source = matcher["label"] == "application source"
    entry = 0 if (is_source and any(name.startswith(p) for p in _SOURCE_PRIORITY)) else 1
    depth = lower.count("/")
    return (entry, depth, lower)


def _get_tree(client: httpx.Client, full_name: str, branch: str) -> list[dict[str, Any]]:
    resp = _get(client, f"/repos/{full_name}/git/trees/{branch}", {"recursive": "1"})
    if resp.status_code != 200:
        return []
    return resp.json().get("tree", []) or []


def _get_raw_file(
    client: httpx.Client, full_name: str, path: str, branch: str, max_bytes: int
) -> Optional[str]:
    try:
        resp = client.get(
            f"/repos/{full_name}/contents/{path}",
            params={"ref": branch},
            headers={"Accept": "application/vnd.github.raw+json"},
        )
    except httpx.HTTPError:
        return None
    if resp.status_code != 200:
        return None
    text = resp.text
    if len(text) > max_bytes:
        text = text[:max_bytes] + f"\n... [truncated at {max_bytes} chars]"
    return text


def build_code_report(
    project_id: str,
    kinds: list[str],
    max_files: int = 20,
    max_per_repo: int = 10,
    max_bytes: int = 20000,
    max_repos: int = 25,
    env: Optional[str] = None,
    branch: Optional[str] = None,
) -> Optional[dict[str, Any]]:
    """Locate and fetch real source files of the given kinds from the project's repos.

    For each mapped repo it resolves the right branch — an explicitly named
    ``branch``, else the branch matching ``env`` (dev -> develop/development,
    uat -> uat, prod -> main/master), else the active integration branch, else
    the default — then scans that branch's tree, matches files by artifact kind
    and fetches their raw contents (read-only, bounded). Returns a formatted
    ``text`` block plus ``meta``. Returns None when no requested kind is known.
    """
    matchers = [_CODE_MATCHERS[k] for k in kinds if k in _CODE_MATCHERS]
    if not matchers:
        return None
    labels = ", ".join(sorted({m["label"] for m in matchers}))

    creds = load_credentials(project_id)
    allowed = _allowed_repos(project_id)
    with _client(creds) as client:
        who = _get(client, "/user")
        if who.status_code in (401, 403):
            raise GitHubApiError(
                f"GitHub token rejected ({who.status_code}): {_error_detail(who)}. "
                "Check the token is valid and has 'repo' + 'read:org' scopes."
            )
        login = who.json().get("login") if who.status_code == 200 else creds.username

        repos = _filter_repos(_list_repos(client, creds), allowed)
        active = [r for r in repos if not r.get("archived")]
        active.sort(
            key=lambda r: 0 if (r.get("language") or "").lower() in _PRIORITY_LANGS else 1
        )

        files: list[dict[str, Any]] = []
        scanned = 0
        branches_used: dict[str, str] = {}
        for repo in active[:max_repos]:
            if len(files) >= max_files:
                break
            full_name = repo.get("full_name")
            if not full_name:
                continue
            default_branch = repo.get("default_branch") or "main"
            use_branch = _resolve_branch(
                _list_branches(client, full_name), default_branch, env, branch
            )
            branches_used[full_name] = use_branch
            scanned += 1
            repo_files = 0
            candidates: list[tuple[str, dict[str, Any]]] = []
            for item in _get_tree(client, full_name, use_branch):
                if item.get("type") != "blob":
                    continue
                path = item.get("path", "")
                matched = next((m for m in matchers if _path_matches(path, m)), None)
                if matched is None:
                    continue
                if matched["label"] == "application source" and any(
                    s in path.lower() for s in _SOURCE_SKIP
                ):
                    continue
                candidates.append((path, matched))
            candidates.sort(key=_candidate_priority)
            for path, matched in candidates:
                if len(files) >= max_files or repo_files >= max_per_repo:
                    break
                content = _get_raw_file(client, full_name, path, use_branch, max_bytes)
                if content is None:
                    continue
                files.append(
                    {
                        "repo": full_name,
                        "path": path,
                        "branch": use_branch,
                        "lang": _lang_for(path, matched["lang"]),
                        "content": content,
                    }
                )
                repo_files += 1

    scope = creds.org or login or "the authenticated account"
    branch_note = ", ".join(
        f"{name.split('/')[-1]}@{br}" for name, br in branches_used.items()
    )
    env_label = f" for the '{env}' environment" if env else ""
    header = (
        f"LIVE GITHUB CODE — {labels} located and fetched read-only from the user's "
        f"repositories just now{env_label}. Review THIS real code and reference the "
        "exact repo/path (and branch) in findings. Do NOT ask the user to paste "
        "files.\n"
        f"Scope: {scope} | branches read: {branch_note or 'default'} | "
        f"repositories scanned: {scanned} | matching files: {len(files)}"
    )
    if not files:
        body = (
            "No matching files were found on the scanned branches "
            f"({branch_note or 'default'}). Tell the user which branches you searched "
            "and that you found none of these files, and ask which repository, branch "
            "or path to look in."
        )
        return {
            "text": header + "\n\n" + body,
            "meta": {"files": 0, "scanned": scanned, "branches": branches_used},
        }

    parts = [header]
    for entry in files:
        parts.append(
            f"### {entry['repo']} — {entry['path']} (branch: {entry['branch']})\n"
            f"```{entry['lang']}\n{entry['content']}\n```"
        )
    return {
        "text": "\n\n".join(parts),
        "meta": {
            "files": len(files),
            "scanned": scanned,
            "scope": scope,
            "branches": branches_used,
        },
    }


def _format_rows(rows: list[dict[str, Any]], limit: int = 60) -> str:
    if not rows:
        return "(none found)"
    shown = rows[:limit]
    lines = [json.dumps(row, default=str, separators=(",", ": ")) for row in shown]
    if len(rows) > limit:
        lines.append(f"... and {len(rows) - limit} more")
    return "\n".join(lines)


def build_environment_report(project_id: str) -> dict[str, Any]:
    """Fetch a live, read-only GitHub security report.

    Returns a dict with a formatted ``text`` block for the LLM plus structured
    ``meta``. Raises GitHubConnectionError / GitHubApiError on failure so the
    caller can surface a precise message.
    """
    creds = load_credentials(project_id)
    allowed = _allowed_repos(project_id)
    with _client(creds) as client:
        who = _get(client, "/user")
        login = who.json().get("login") if who.status_code == 200 else creds.username
        if who.status_code in (401, 403):
            raise GitHubApiError(
                f"GitHub token rejected ({who.status_code}): {_error_detail(who)}. "
                "Check the token is valid and has 'repo' + 'read:org' scopes."
            )

        repos = _filter_repos(_list_repos(client, creds), allowed)

        sections: list[str] = []
        scope = creds.org or login or "the authenticated account"
        sections.append(f"GitHub scope: {scope}")
        sections.append(f"Repositories returned: {len(repos)}")

        public = [r for r in repos if not r.get("private")]
        archived = [r for r in repos if r.get("archived")]
        sections.append(
            f"Public repositories: {len(public)} | Private: {len(repos) - len(public)} "
            f"| Archived: {len(archived)}"
        )

        languages: dict[str, int] = {}
        for repo in repos:
            lang = repo.get("language") or "unknown"
            languages[lang] = languages.get(lang, 0) + 1
        if languages:
            lang_lines = "\n".join(
                f"- {name}: {count}"
                for name, count in sorted(languages.items(), key=lambda kv: -kv[1])[:20]
            )
            sections.append("Repositories by language:\n" + lang_lines)

        inventory = [
            {
                "name": r.get("full_name") or r.get("name"),
                "visibility": "private" if r.get("private") else "public",
                "archived": bool(r.get("archived")),
                "defaultBranch": r.get("default_branch"),
                "pushedAt": r.get("pushed_at"),
                "language": r.get("language"),
            }
            for r in repos[:_MAX_REPOS]
        ]
        sections.append(
            "Repository inventory (name, visibility, defaultBranch, pushedAt):\n"
            + _format_rows(inventory, limit=_MAX_REPOS)
        )

        if public:
            pub_rows = [{"name": r.get("full_name") or r.get("name")} for r in public]
            sections.append(
                "Public repositories (confirm each is intended to be public):\n"
                + _format_rows(pub_rows)
            )

        probe_rows: list[dict[str, Any]] = []
        for repo in repos[:_PROBE_REPOS]:
            full_name = repo.get("full_name")
            branch = repo.get("default_branch") or "main"
            if not full_name:
                continue
            row = {
                "repo": full_name,
                "defaultBranch": branch,
                "branchProtection": _branch_protection(client, full_name, branch),
                "vulnerabilityAlerts": _vuln_alerts(client, full_name),
            }
            row["dependabotAlerts"] = _dependabot_alerts(client, full_name)
            probe_rows.append(row)
        sections.append(
            "Default-branch protection & Dependabot alerts "
            f"(top {len(probe_rows)} by recent activity):\n" + _format_rows(probe_rows)
        )

    text = "\n\n".join(sections)
    return {
        "text": text,
        "meta": {
            "scope": creds.org or login,
            "repo_count": len(repos),
            "public_count": len(public),
        },
    }


def list_repos_for_picker(project_id: str, limit: int = 100) -> list[dict[str, Any]]:
    """Return repo metadata for onboarding picker (unfiltered by project mapping)."""
    creds = load_credentials(project_id)
    with _client(creds) as client:
        who = _get(client, "/user")
        if who.status_code in (401, 403):
            raise GitHubApiError(
                f"GitHub token rejected ({who.status_code}): {_error_detail(who)}."
            )
        repos = _list_repos(client, creds)
    out: list[dict[str, Any]] = []
    for repo in repos[: max(1, min(limit, 200))]:
        out.append(
            {
                "full_name": repo.get("full_name"),
                "name": repo.get("name"),
                "private": bool(repo.get("private")),
                "html_url": repo.get("html_url"),
                "default_branch": repo.get("default_branch"),
                "description": (repo.get("description") or "")[:200],
            }
        )
    return out


def create_repo(
    project_id: str,
    *,
    name: str,
    private: bool = True,
    org: Optional[str] = None,
    description: str = "",
    auto_init: bool = True,
) -> dict[str, Any]:
    """Create a repository on the authenticated user or org account."""
    clean = (name or "").strip()
    if not clean or "/" in clean or not re.match(r"^[A-Za-z0-9_.-]+$", clean):
        raise ValueError("Invalid repository name")
    creds = load_credentials(project_id)
    payload = {
        "name": clean,
        "private": bool(private),
        "description": (description or "Created by InfraLens")[:350],
        "auto_init": bool(auto_init),
    }
    org_name = (org or creds.org or "").strip() or None
    path = f"/orgs/{org_name}/repos" if org_name else "/user/repos"
    with _client(creds) as client:
        try:
            resp = client.post(path, json=payload)
        except httpx.HTTPError as exc:
            raise GitHubApiError(f"GitHub request failed: {exc}") from exc
        if resp.status_code not in (200, 201):
            raise GitHubApiError(
                f"Could not create repository ({resp.status_code}): {_error_detail(resp)}"
            )
        body = resp.json()
    return {
        "full_name": body.get("full_name"),
        "html_url": body.get("html_url"),
        "private": bool(body.get("private")),
        "default_branch": body.get("default_branch") or "main",
        "clone_url": body.get("clone_url"),
    }
