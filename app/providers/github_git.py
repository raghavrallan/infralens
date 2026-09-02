"""Project-isolated GitHub writes (branch + PR) using that project's token.

Never uses another project's credentials. Only mapped repositories are allowed.
Does not push terraform state or .terraform directories.
"""
from __future__ import annotations

import re
from typing import Any

from app.providers import github_infra
from app.tenancy import projects

_PREFIX = "infra/infralens"
_SAFE_FILE = re.compile(r"^[A-Za-z0-9._/-]+\.(tf|md|yml|yaml|py)$")


def mapped_repo(project_id: str) -> str:
    repos = [item.strip() for item in projects.get_repos(project_id) if str(item).strip()]
    if not repos:
        raise ValueError("Map a GitHub repository on this project before pushing IaC.")
    preferred = [item for item in repos if "infra" in item.lower() or "iac" in item.lower()]
    return (preferred or repos)[0]


def repo_prefix(project_id: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9._-]+", "-", project_id)[:40] or "project"
    return f"{_PREFIX}/{slug}"


def assert_mapped(project_id: str, full_name: str) -> None:
    allowed = {item.lower() for item in projects.get_repos(project_id)}
    if full_name.lower() not in allowed:
        raise ValueError("GitHub write target is outside the repositories mapped to this project")


def push_files_pr(
    project_id: str,
    files: dict[str, str],
    *,
    branch: str,
    title: str,
    body: str = "",
    path_prefix: str = "",
) -> dict[str, Any]:
    """Commit files on an isolated branch and open a PR against the default branch."""
    if not files:
        raise ValueError("No files to push")
    repo = mapped_repo(project_id)
    assert_mapped(project_id, repo)
    prefix = (path_prefix or repo_prefix(project_id)).strip("/").replace("\\", "/")
    if ".." in prefix.split("/"):
        raise ValueError("Unsafe GitHub path prefix")
    tree_items: list[dict[str, str]] = []
    for name, content in files.items():
        clean = name.replace("\\", "/").lstrip("/")
        if ".." in clean.split("/") or not _SAFE_FILE.match(clean.split("/")[-1] if "/" in clean else clean):
            raise ValueError(f"Refusing to push unsafe path: {name}")
        rel = f"{prefix}/{clean.split('/')[-1]}"
        tree_items.append(
            {
                "path": rel,
                "mode": "100644",
                "type": "blob",
                "content": content or "",
            }
        )
    creds = github_infra.load_credentials(project_id)
    owner, name = repo.split("/", 1)
    with github_infra._client(creds) as client:
        meta = github_infra._get(client, f"/repos/{owner}/{name}")
        if meta.status_code != 200:
            raise github_infra.GitHubApiError(
                f"Could not read {repo} ({meta.status_code}): {github_infra._error_detail(meta)}"
            )
        default_branch = str((meta.json() or {}).get("default_branch") or "main")
        ref = github_infra._get(client, f"/repos/{owner}/{name}/git/ref/heads/{default_branch}")
        if ref.status_code != 200:
            raise github_infra.GitHubApiError(
                f"Could not read default branch ({ref.status_code}): {github_infra._error_detail(ref)}"
            )
        base_sha = str((ref.json() or {}).get("object", {}).get("sha") or "")
        if not base_sha:
            raise github_infra.GitHubApiError("Default branch has no commit SHA")
        commit = github_infra._get(client, f"/repos/{owner}/{name}/git/commits/{base_sha}")
        if commit.status_code != 200:
            raise github_infra.GitHubApiError(
                f"Could not read base commit ({commit.status_code}): {github_infra._error_detail(commit)}"
            )
        base_tree = str((commit.json() or {}).get("tree", {}).get("sha") or "")
        tree_resp = client.post(
            f"/repos/{owner}/{name}/git/trees",
            json={"base_tree": base_tree, "tree": tree_items},
        )
        if tree_resp.status_code not in {200, 201}:
            raise github_infra.GitHubApiError(
                f"Could not create tree ({tree_resp.status_code}): {github_infra._error_detail(tree_resp)}"
            )
        tree_sha = str((tree_resp.json() or {}).get("sha") or "")
        commit_resp = client.post(
            f"/repos/{owner}/{name}/git/commits",
            json={
                "message": title[:200],
                "tree": tree_sha,
                "parents": [base_sha],
            },
        )
        if commit_resp.status_code not in {200, 201}:
            raise github_infra.GitHubApiError(
                f"Could not create commit ({commit_resp.status_code}): {github_infra._error_detail(commit_resp)}"
            )
        commit_sha = str((commit_resp.json() or {}).get("sha") or "")
        branch_ref = f"refs/heads/{branch}"
        created = client.post(
            f"/repos/{owner}/{name}/git/refs",
            json={"ref": branch_ref, "sha": commit_sha},
        )
        if created.status_code == 422:
            updated = client.patch(
                f"/repos/{owner}/{name}/git/refs/heads/{branch}",
                json={"sha": commit_sha, "force": False},
            )
            if updated.status_code not in {200, 201}:
                raise github_infra.GitHubApiError(
                    f"Could not update branch ({updated.status_code}): {github_infra._error_detail(updated)}"
                )
        elif created.status_code not in {200, 201}:
            raise github_infra.GitHubApiError(
                f"Could not create branch ({created.status_code}): {github_infra._error_detail(created)}"
            )
        pr_url = ""
        pr_number = None
        existing = github_infra._get(
            client,
            f"/repos/{owner}/{name}/pulls",
            {"head": f"{owner}:{branch}", "state": "open"},
        )
        if existing.status_code == 200 and existing.json():
            pr = existing.json()[0]
            pr_url = str(pr.get("html_url") or "")
            pr_number = pr.get("number")
        else:
            opened = client.post(
                f"/repos/{owner}/{name}/pulls",
                json={
                    "title": title[:200],
                    "head": branch,
                    "base": default_branch,
                    "body": (body or title)[:4000],
                },
            )
            if opened.status_code not in {200, 201}:
                raise github_infra.GitHubApiError(
                    f"Commit pushed but PR failed ({opened.status_code}): {github_infra._error_detail(opened)}"
                )
            pr = opened.json()
            pr_url = str(pr.get("html_url") or "")
            pr_number = pr.get("number")
    return {
        "repo": repo,
        "branch": branch,
        "base": default_branch,
        "commit": commit_sha,
        "pr_url": pr_url,
        "pr_number": pr_number,
        "files": [item["path"] for item in tree_items],
        "prefix": prefix,
    }
