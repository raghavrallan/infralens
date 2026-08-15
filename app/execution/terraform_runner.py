"""Terraform workspace management and gated init/validate/plan/apply actions.

Terraform write phases create structured execution jobs with plan summaries and
machine-executable rollback operations. The provider queue remains the dispatch
path; validation accepts the ``terraform`` executable under provider
``terraform``.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any, Optional
from uuid import uuid4

from app.platform import connections
from app.execution import service

_WORKSPACE_ROOT = Path(
    os.environ.get(
        "TERRAFORM_WORKSPACE_ROOT",
        str(Path.cwd() / ".terraform-workspaces"),
    )
)
_SAFE_NAME = re.compile(r"^[a-zA-Z0-9._-]{1,80}$")
_PLAN_COUNTS = re.compile(
    r"Plan:\s*(\d+)\s*to add,\s*(\d+)\s*to change,\s*(\d+)\s*to destroy",
    re.IGNORECASE,
)


def workspace_dir(project_id: str, name: str = "default") -> Path:
    if not _SAFE_NAME.match(name):
        raise ValueError("Invalid Terraform workspace name")
    path = _WORKSPACE_ROOT / project_id / name
    path.mkdir(parents=True, exist_ok=True)
    return path


def write_files(project_id: str, files: dict[str, str], name: str = "default") -> Path:
    """Persist generated Terraform files into the project workspace."""
    root = workspace_dir(project_id, name)
    for relative, content in files.items():
        clean = relative.replace("\\", "/").lstrip("/")
        if ".." in clean.split("/"):
            raise ValueError(f"Unsafe Terraform path: {relative}")
        target = root / clean
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content or "", encoding="utf-8")
    return root


def extract_files_from_markdown(markdown: str) -> dict[str, str]:
    """Pull fenced HCL/TF blocks that declare filenames from skill output."""
    files: dict[str, str] = {}
    pattern = re.compile(
        r"```(?:hcl|terraform|tf)?\s*(?:file[=:]?\s*)?([A-Za-z0-9_./-]+\.tf(?:vars)?)\s*\n(.*?)```",
        re.IGNORECASE | re.DOTALL,
    )
    for match in pattern.finditer(markdown or ""):
        files[match.group(1).strip()] = match.group(2).strip() + "\n"
    # Also accept headings like ### main.tf followed by a fence.
    heading = re.compile(
        r"(?:^|\n)#{1,3}\s*([A-Za-z0-9_./-]+\.tf(?:vars)?)\s*\n```(?:hcl|terraform|tf)?\s*\n(.*?)```",
        re.IGNORECASE | re.DOTALL,
    )
    for match in heading.finditer(markdown or ""):
        files.setdefault(match.group(1).strip(), match.group(2).strip() + "\n")
    return files


def parse_plan_summary(plan_text: str) -> dict[str, Any]:
    match = _PLAN_COUNTS.search(plan_text or "")
    if not match:
        return {"add": None, "change": None, "destroy": None, "raw_excerpt": (plan_text or "")[:2000]}
    return {
        "add": int(match.group(1)),
        "change": int(match.group(2)),
        "destroy": int(match.group(3)),
        "raw_excerpt": (plan_text or "")[:2000],
    }


def blast_radius_for_plan(summary: dict[str, Any]) -> str:
    destroy = int(summary.get("destroy") or 0)
    change = int(summary.get("change") or 0)
    add = int(summary.get("add") or 0)
    if destroy >= 5 or (destroy and change >= 10):
        return "high"
    if destroy or change >= 5 or add >= 20:
        return "medium"
    return "low"


def _terraform_available() -> bool:
    return shutil.which("terraform") is not None


def run_local_phase(
    project_id: str,
    phase: str,
    *,
    name: str = "default",
    auto_approve: bool = False,
    timeout: int = 300,
) -> dict[str, Any]:
    """Run a local terraform phase when the binary is available (dev/control plane)."""
    if phase not in {"init", "validate", "plan", "apply", "destroy"}:
        raise ValueError("Unsupported Terraform phase")
    if not _terraform_available():
        raise RuntimeError(
            "Terraform CLI is not installed on this host. "
            "Queue a provider.terraform action or install Terraform locally."
        )
    root = workspace_dir(project_id, name)
    argv = ["terraform", "-chdir=" + str(root), phase]
    if phase == "init":
        argv.append("-input=false")
    elif phase == "plan":
        argv.extend(["-input=false", "-no-color", "-out=tfplan"])
    elif phase in {"apply", "destroy"}:
        argv.extend(["-input=false", "-no-color"])
        if phase == "apply" and (root / "tfplan").exists():
            argv.append("tfplan")
        elif auto_approve:
            argv.append("-auto-approve")
    completed = subprocess.run(
        argv,
        shell=False,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
        env=os.environ.copy(),
    )
    stdout = (completed.stdout or "")[:200000]
    stderr = (completed.stderr or "")[:200000]
    result = {
        "phase": phase,
        "returncode": completed.returncode,
        "stdout": stdout,
        "stderr": stderr,
        "workspace": str(root),
    }
    if phase == "plan":
        result["plan_summary"] = parse_plan_summary(stdout + "\n" + stderr)
        result["blast_radius"] = blast_radius_for_plan(result["plan_summary"])
    return result


def _cloud_provider_for_project(project_id: str) -> str:
    if connections.get_secret_fields(project_id, "azure"):
        return "azure"
    if connections.get_secret_fields(project_id, "aws"):
        return "aws"
    return "azure"


def build_rollback_operation(
    phase: str,
    workspace_name: str,
    plan_summary: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """Machine-executable rollback for Terraform write phases."""
    if phase == "destroy":
        # Destroy already moves toward absence; rollback is re-apply last plan.
        return {
            "provider": "terraform",
            "executable": "terraform",
            "args": ["apply", "-input=false", "-auto-approve", "tfplan.previous"],
            "target": f"workspace/{workspace_name}",
            "access_scope": "write",
            "expected_result": "Previous Terraform plan re-applied after a failed destroy.",
            "risk": "Restores prior infrastructure from the saved plan artifact.",
            "rollback": "Manual recovery required if prior plan artifact is unavailable.",
            "preflight": ["version"],
            "verify": ["show", "-json"],
        }
    destroy_count = int((plan_summary or {}).get("destroy") or 0)
    if destroy_count:
        note = "Review state backup before rolling back destructive applies."
    else:
        note = "Targeted destroy of resources created by this apply."
    return {
        "provider": "terraform",
        "executable": "terraform",
        "args": ["apply", "-destroy", "-input=false", "-auto-approve", "-target=module.rollback_scope"],
        "target": f"workspace/{workspace_name}",
        "access_scope": "write",
        "expected_result": "Resources created by the failed/unwanted apply are removed.",
        "risk": note,
        "rollback": "No further automatic rollback after destroy of the apply scope.",
        "preflight": ["state", "list"],
        "verify": ["state", "list"],
        "preflight_expect": "",
    }


def create_terraform_action(
    *,
    project_id: str,
    phase: str,
    workspace_name: str = "default",
    access_level: str = "ask_approval",
    requested_by: str = "chat",
    plan_summary: Optional[dict[str, Any]] = None,
    why: str = "",
) -> dict[str, Any]:
    """Create a gated Terraform action for the execution control plane."""
    if phase not in {"init", "validate", "plan", "apply", "destroy"}:
        raise ValueError("Unsupported Terraform phase")
    workspace_dir(project_id, workspace_name)
    access_scope = "write" if phase in {"apply", "destroy"} else "read_only"
    summary = plan_summary or {}
    blast = blast_radius_for_plan(summary) if summary else ("high" if phase == "destroy" else "medium")
    rollback_op = build_rollback_operation(phase, workspace_name, summary)
    args = [phase, "-input=false", "-no-color"]
    if phase == "plan":
        args.extend(["-out=tfplan"])
    if phase in {"apply", "destroy"}:
        args.append("-auto-approve")
        if phase == "apply":
            args = ["apply", "-input=false", "-no-color", "-auto-approve", "tfplan"]
    expected = {
        "init": "Terraform providers initialized for the workspace.",
        "validate": "Terraform configuration is valid.",
        "plan": "Terraform plan produced and saved as tfplan.",
        "apply": "Terraform apply completed and resources match the approved plan.",
        "destroy": "Terraform destroy completed for the targeted workspace scope.",
    }[phase]
    risk = {
        "init": "Downloads providers; no infrastructure changes.",
        "validate": "Static validation only; no infrastructure changes.",
        "plan": "Read-only planning against remote APIs; no infrastructure changes.",
        "apply": "Applies the approved Terraform plan to live infrastructure.",
        "destroy": "Destroys infrastructure managed by this Terraform workspace.",
    }[phase]
    return service.create_action(
        project_id=project_id,
        provider="terraform",
        executable="terraform",
        args=args,
        target=f"workspace/{workspace_name}",
        access_scope=access_scope,
        expected_result=expected,
        risk=risk,
        rollback=json.dumps(rollback_op) if access_scope == "write" else "Not applicable",
        preflight=["version"] if access_scope == "write" else [],
        preflight_expect="",
        verify=["show", "-json"] if access_scope == "write" else [],
        requested_by=requested_by,
        access_level=access_level,
        why=why or f"Terraform {phase} for workspace {workspace_name}",
        blast_radius=blast,
        degrade_plan="Stop traffic / disable canary before broader rollback if health checks fail.",
        rollback_operation=rollback_op if access_scope == "write" else None,
        cloud_provider=_cloud_provider_for_project(project_id),
    )


def prepare_from_skill_output(
    project_id: str,
    markdown: str,
    *,
    workspace_name: str = "default",
) -> dict[str, Any]:
    """Persist HCL from terraform_generator output and return workspace metadata."""
    files = extract_files_from_markdown(markdown)
    if not files:
        raise ValueError("No Terraform files were found in the generator output")
    root = write_files(project_id, files, workspace_name)
    return {
        "workspace": str(root),
        "workspace_name": workspace_name,
        "files": sorted(files.keys()),
        "file_count": len(files),
    }


def pipeline(
    project_id: str,
    *,
    workspace_name: str = "default",
    access_level: str = "ask_approval",
    requested_by: str = "chat",
    run_local_plan: bool = True,
) -> dict[str, Any]:
    """Run init/validate/(local plan) then create an approval-gated apply action."""
    phases: list[dict[str, Any]] = []
    for phase in ("init", "validate"):
        if _terraform_available():
            result = run_local_phase(project_id, phase, name=workspace_name)
            phases.append(result)
            if result["returncode"] != 0:
                return {"ok": False, "phases": phases, "error": f"terraform {phase} failed"}
        else:
            phases.append({"phase": phase, "skipped": True, "reason": "terraform binary unavailable"})
    plan_summary: dict[str, Any] = {}
    if run_local_plan and _terraform_available():
        plan = run_local_phase(project_id, "plan", name=workspace_name)
        phases.append(plan)
        plan_summary = plan.get("plan_summary") or {}
        if plan["returncode"] not in {0, 2}:
            return {"ok": False, "phases": phases, "error": "terraform plan failed"}
    action = create_terraform_action(
        project_id=project_id,
        phase="apply",
        workspace_name=workspace_name,
        access_level=access_level,
        requested_by=requested_by,
        plan_summary=plan_summary,
        why="Approved Terraform apply after init/validate/plan",
    )
    return {
        "ok": True,
        "phases": phases,
        "plan_summary": plan_summary,
        "action": action,
        "id": str(uuid4()),
    }
