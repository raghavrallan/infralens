"""CI/CD watchers: GitHub Actions / Azure DevOps run status and retry hooks."""
from __future__ import annotations

import time
from typing import Any, Optional

from app.tenancy import projects
from app.execution import debug_loop, queue, service
from app.providers import github_infra


def watch_github_workflow_runs(
    project_id: str,
    *,
    limit: int = 10,
) -> list[dict[str, Any]]:
    """Return recent workflow runs for repositories mapped to the project."""
    if not github_infra.is_connected(project_id):
        return []
    repos = projects.get_repos(project_id)
    if not repos:
        return []
    creds = github_infra.load_credentials(project_id)
    results: list[dict[str, Any]] = []
    with github_infra._client(creds) as client:
        for repo in repos[:15]:
            resp = github_infra._get(
                client,
                f"/repos/{repo}/actions/runs",
                params={"per_page": min(limit, 20)},
            )
            if resp.status_code >= 400:
                results.append(
                    {
                        "repo": repo,
                        "error": github_infra._error_detail(resp),
                        "runs": [],
                    }
                )
                continue
            body = resp.json() if resp.content else {}
            runs = []
            for item in (body.get("workflow_runs") or [])[:limit]:
                runs.append(
                    {
                        "id": item.get("id"),
                        "name": item.get("name"),
                        "status": item.get("status"),
                        "conclusion": item.get("conclusion"),
                        "html_url": item.get("html_url"),
                        "head_branch": item.get("head_branch"),
                        "event": item.get("event"),
                        "updated_at": item.get("updated_at"),
                    }
                )
            results.append({"repo": repo, "runs": runs, "error": ""})
    return results


def failed_runs(project_id: str) -> list[dict[str, Any]]:
    """Flatten recent failed/cancelled workflow runs."""
    failed: list[dict[str, Any]] = []
    for repo_block in watch_github_workflow_runs(project_id, limit=8):
        repo = repo_block.get("repo")
        for run in repo_block.get("runs") or []:
            if run.get("conclusion") in {"failure", "timed_out", "cancelled"}:
                failed.append({"repo": repo, **run})
    return failed


def create_rerun_action(
    project_id: str,
    repo: str,
    run_id: int | str,
    *,
    access_level: str = "ask_approval",
    requested_by: str = "cicd",
) -> dict[str, Any]:
    """Queue a GitHub CLI action to re-run a failed workflow run."""
    return service.create_action(
        project_id=project_id,
        provider="github",
        executable="gh",
        args=["run", "rerun", str(run_id), "--repo", repo],
        target=repo,
        access_scope="write",
        expected_result=f"GitHub Actions run {run_id} re-queued for {repo}.",
        risk="Re-runs an existing workflow; may redeploy artifacts depending on the workflow.",
        rollback=(
            '{"provider":"github","executable":"gh","args":["run","cancel","'
            + str(run_id)
            + '","--repo","'
            + repo
            + '"],"target":"'
            + repo
            + '","expected_result":"Cancel the re-run if it is unsafe."}'
        ),
        preflight=["run", "view", str(run_id), "--repo", repo, "--json", "status,conclusion"],
        verify=["run", "view", str(run_id), "--repo", repo, "--json", "status,conclusion"],
        requested_by=requested_by,
        access_level=access_level,
        why=f"Retry failed CI/CD run {run_id}",
        blast_radius="medium",
    )


def wait_for_action(
    action_id: str,
    *,
    timeout: float = 120.0,
    poll: float = 2.0,
) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        current = service.get_action(action_id)
        if current.get("status") in service.TERMINAL | {"awaiting_approval"}:
            return current
        time.sleep(poll)
    return service.get_action(action_id)


def auto_retry_failed_builds(
    project_id: str,
    *,
    access_level: str = "ask_approval",
    limit: int = 3,
) -> dict[str, Any]:
    """Prepare gated re-run actions for recent failed builds (does not auto-approve)."""
    prepared: list[dict[str, Any]] = []
    for run in failed_runs(project_id)[:limit]:
        try:
            action = create_rerun_action(
                project_id,
                str(run["repo"]),
                run["id"],
                access_level=access_level,
            )
            prepared.append({"run": run, "action": action})
        except Exception as exc:  # noqa: BLE001
            prepared.append({"run": run, "error": str(exc)[:300]})
    payload = {
        "failed_count": len(failed_runs(project_id)),
        "prepared": prepared,
        "queue_hint": (
            "Approve write actions; the org provider.github.write worker must be running "
            "(Organizations → Executor capacity)."
        ),
        "queue_snapshot": {},
    }
    try:
        from app.org_executors import settings as org_executor_settings

        org_id = org_executor_settings.resolve_org_id_for_project(project_id)
        payload["queue_snapshot"] = queue.queue_snapshot(org_id, "github", "write")
    except Exception as exc:  # noqa: BLE001
        payload["queue_snapshot"] = {"diagnostic_error": str(exc)[:300]}
    return payload


def after_success_deploy_hook(
    project_id: str,
    *,
    workspace_name: str = "default",
    access_level: str = "ask_approval",
) -> dict[str, Any]:
    """When CI is green, prepare the Terraform/deploy apply gate."""
    from app.execution import deploy_orchestrator

    runs = watch_github_workflow_runs(project_id, limit=5)
    latest_ok = False
    for block in runs:
        for run in block.get("runs") or []:
            if run.get("status") == "completed" and run.get("conclusion") == "success":
                latest_ok = True
                break
        if latest_ok:
            break
    if not latest_ok and runs:
        return {
            "ok": False,
            "message": "No successful recent workflow run found; deploy not prepared.",
            "runs": runs,
        }
    return deploy_orchestrator.run_deploy_pipeline(
        project_id,
        workspace_name=workspace_name,
        access_level=access_level,
        requested_by="cicd",
    )


def debug_failed_run(
    project_id: str,
    action_id: str,
    *,
    chat_id: Optional[str] = None,
) -> dict[str, Any]:
    return debug_loop.run_debug_cycle(
        action_id,
        chat_id=chat_id,
        project_context=f"project_id={project_id}",
    )
