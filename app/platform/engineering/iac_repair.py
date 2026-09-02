"""Azure OpenAI repair loop for isolated Terraform init/plan/apply.

Keeps one conversation on the delivery run so later phases still see what
failed and what already changed.
"""
from __future__ import annotations

import json
import re
import uuid
from pathlib import Path
from typing import Any

from sqlalchemy import select

from app.core import azure_client, config as app_config
from app.core.db import ProjectArtifact, SessionLocal, _now
from app.platform.engineering.artifacts import MAX_TEXT

MAX_ATTEMPTS = 4
MAX_TURNS = 16
_PUSHABLE = re.compile(r"\.(tf|md|yml|yaml|py)$", re.IGNORECASE)
_REDACT = re.compile(
    r"(?im)((?:client_secret|secret_access_key|password|api[_-]?key|token|"
    r"ARM_CLIENT_SECRET|AWS_SECRET_ACCESS_KEY)\s*[:=]\s*)(\S+)"
)
_SYSTEM = """You fix Terraform for an InfraLens isolated workspace.
The workspace uses a local backend (terraform.tfstate). Do not switch to a remote backend.
Do not invent cloud credentials. Do not replace real resources with null_resource.
Return JSON only:
{
  "diagnosis": "what failed and why",
  "files": {"filename.tf": "full replacement contents"},
  "unfixable": false
}
Only include files that must change. Use complete file bodies, not diffs.
Set unfixable=true when the error is credentials, quota, RBAC, or missing Azure subscription access.
If Azure says a resource already exists and must be imported, do not convert it to a data source and do not rename it. Leave the resource block as-is so InfraLens can import it.
If Azure returns ParameterOutOfRange with Version should be in: [], that is NOT a missing-version bug. Do not remove `version`. Do not only swap 15 and 16. It usually means PostgreSQL Flexible Server cannot be provisioned in the current location (eastus is often restricted). Keep existing resources in their current region. Create PostgreSQL in another region such as eastus2 without cross-region delegated_subnet_id or private_dns_zone_id, and keep an explicit version (16 or 15) plus a valid sku.
If you move PostgreSQL to another region, you MUST remove delegated_subnet_id and private_dns_zone_id. A VNet in eastus cannot back a server in eastus2. Use public_network_access_enabled = true for that server.
If Azure returns 409 InvalidResourceLocation because the server already exists in location X, set location = "X", drop VNet injection, keep version, and do not recreate it in eastus.
If Azure says version is required when create_mode is Default, put `version` back. Never oscillate between adding and removing version; change location or SKU instead.
If terraform destroy / revert is blocked by lifecycle prevent_destroy, remove those prevent_destroy blocks so this isolated stack can be torn down. Do not add new cloud resources during a destroy repair.
Keep prior repairs. Do not revert working files without a reason."""


def redact(text: str) -> str:
    return _REDACT.sub(r"\1***", text or "")


def existing_context(artifacts: dict[str, Any] | None) -> dict[str, Any]:
    raw = dict((artifacts or {}).get("terraform_repair") or {})
    turns = [item for item in (raw.get("turns") or []) if isinstance(item, dict)]
    return {
        "status": str(raw.get("status") or "idle"),
        "phase": str(raw.get("phase") or ""),
        "progress": str(raw.get("progress") or ""),
        "turns": turns[-MAX_TURNS:],
    }


def slim_architecture(artifacts: dict[str, Any] | None) -> dict[str, Any]:
    proposal = dict((artifacts or {}).get("architecture_proposal") or {})
    model = proposal.get("architecture") if isinstance(proposal.get("architecture"), dict) else {}
    return {
        "cloud": model.get("cloud") or proposal.get("mode") or "",
        "summary": str(proposal.get("summary") or "")[:800],
        "components": [
            {
                "name": item.get("name"),
                "service": item.get("service"),
                "purpose": item.get("purpose"),
            }
            for item in (model.get("components") or [])[:20]
            if isinstance(item, dict)
        ],
        "iac_strategy": str(model.get("iac_strategy") or "")[:400],
    }


def files_for_prompt(files: dict[str, str], *, budget: int = 40_000) -> str:
    parts: list[str] = []
    used = 0
    for name in sorted(files):
        body = (files.get(name) or "")[:12_000]
        block = f"### {name}\n```\n{body}\n```\n"
        if used + len(block) > budget:
            break
        parts.append(block)
        used += len(block)
    return "".join(parts) or "(no terraform files)"


def turns_for_prompt(turns: list[dict[str, Any]]) -> str:
    lines: list[str] = []
    for item in turns[-8:]:
        lines.append(
            f"- phase={item.get('phase')} attempt={item.get('attempt')} "
            f"files={', '.join(item.get('files') or []) or 'none'}\n"
            f"  diagnosis: {redact(str(item.get('diagnosis') or ''))[:600]}\n"
            f"  error: {redact(str(item.get('error') or ''))[:800]}"
        )
    return "\n".join(lines) or "(no prior repair turns — keep this context going)"


def repair_hints(error: str, turns: list[dict[str, Any]] | None = None) -> str:
    """Error-specific guidance so repair does not oscillate on the wrong field."""
    err = error or ""
    err_l = err.lower().replace("`", "")
    hints: list[str] = []
    empty_version = (
        "should be in: []" in err
        or "should be in:[]" in err_l
        or ("parameteroutofrange" in err_l and "version" in err_l)
    )
    if empty_version:
        hints.append(
            "Empty Azure Version list is not a missing-version bug. Keep an explicit "
            "`version` (16 or 15). Do not delete version. PostgreSQL Flexible Server is "
            "often restricted in eastus; create it in eastus2 (or centralus) without "
            "cross-region delegated_subnet_id/private_dns_zone_id."
        )
    if "version is required" in err_l:
        hints.append(
            "Azure requires `version` for Default create_mode. Put version = \"16\" (or \"15\") back. "
            "Do not remove it on the next turn."
        )
    if "invalidresourcelocation" in err_l and "already exists in location" in err_l:
        hints.append(
            "The PostgreSQL server name already exists in another region. Set location to that "
            "existing region, remove delegated_subnet_id and private_dns_zone_id, keep version, "
            "and do not recreate the server in eastus."
        )
    if "vnet" in err_l and "location" in err_l:
        hints.append(
            "Do not attach an eastus delegated subnet or private DNS zone to a PostgreSQL server "
            "in eastus2. Remove those arguments when the server location changes."
        )
    if "already exists" in err_l and "imported" in err_l:
        hints.append(
            "Do not convert the existing Azure resource to a data source or rename it. "
            "Leave the resource block unchanged so InfraLens can import it."
        )
    if "prevent_destroy" in err_l:
        hints.append(
            "Destroy/revert is blocked by lifecycle. Remove prevent_destroy from the "
            "blocking resources so InfraLens can tear down this isolated stack. Do not add resources."
        )
    recent = " ".join(str(item.get("diagnosis") or "") for item in (turns or [])[-4:]).lower()
    if empty_version and ("version is required" in recent or "missing" in recent and "version" in recent):
        hints.append(
            "Prior turns already oscillated on version. Change location or SKU this turn, not version."
        )
    return "\n".join(f"- {hint}" for hint in hints)


def propose_fix(
    *,
    phase: str,
    error: str,
    files: dict[str, str],
    architecture: dict[str, Any],
    turns: list[dict[str, Any]],
) -> dict[str, Any]:
    if not app_config.get_azure_config().configured:
        raise azure_client.AzureOpenAINotConfiguredError(
            "Azure OpenAI is not configured. Open Settings and add the platform "
            "endpoint and API key so Terraform errors can be repaired."
        )
    user = (
        f"Phase that failed: {phase}\n\n"
        f"Architecture:\n{json.dumps(architecture, indent=2)[:2500]}\n\n"
        f"Prior repair context (do not lose this):\n{turns_for_prompt(turns)}\n\n"
        f"Repair hints:\n{repair_hints(error, turns) or '(none)'}\n\n"
        f"Current files:\n{files_for_prompt(files)}\n\n"
        f"Terraform error:\n{redact(error)[:4000]}"
    )
    completion = azure_client.chat(
        [{"role": "system", "content": _SYSTEM}, {"role": "user", "content": user}],
        temperature=0.1,
        response_format={"type": "json_object"},
        name=f"terraform-repair-{phase}",
    )
    content = completion.choices[0].message.content or "{}"
    parsed = json.loads(content)
    if not isinstance(parsed, dict):
        raise RuntimeError("Azure OpenAI returned a non-object Terraform repair response")
    raw_files = parsed.get("files") if isinstance(parsed.get("files"), dict) else {}
    safe_files = {
        Path(str(name).replace("\\", "/")).name: str(body)
        for name, body in raw_files.items()
        if isinstance(body, str) and body.strip()
    }
    return {
        "diagnosis": str(parsed.get("diagnosis") or "No diagnosis returned"),
        "files": safe_files,
        "unfixable": bool(parsed.get("unfixable")),
    }


def apply_file_updates(
    project_id: str,
    delivery_run_id: str,
    files: dict[str, str],
) -> list[str]:
    changed: list[str] = []
    with SessionLocal() as session:
        rows = session.scalars(
            select(ProjectArtifact).where(
                ProjectArtifact.project_id == project_id,
                ProjectArtifact.delivery_run_id == delivery_run_id,
            )
        ).all()
        by_name = {
            Path(row.filename or row.name or "").name: row
            for row in rows
            if Path(row.filename or row.name or "").name
        }
        for raw_name, content in (files or {}).items():
            name = Path(str(raw_name).replace("\\", "/")).name
            if not name or ".." in str(raw_name) or not _PUSHABLE.search(name):
                continue
            if not isinstance(content, str) or not content.strip():
                continue
            body = content[:MAX_TEXT]
            row = by_name.get(name)
            if row is not None:
                row.content_text = body
                row.origin = "azure_openai_repair"
                row.version = int(row.version or 1) + 1
                row.updated_at = _now()
            else:
                session.add(
                    ProjectArtifact(
                        id=str(uuid.uuid4()),
                        project_id=project_id,
                        delivery_run_id=delivery_run_id,
                        name=name,
                        filename=name,
                        kind="terraform" if name.endswith(".tf") else "",
                        mime="text/plain",
                        origin="azure_openai_repair",
                        content_text=body,
                        created_by="azure-openai-repair",
                        version=1,
                    )
                )
            changed.append(name)
        session.commit()
    return changed


def record_turn(
    turns: list[dict[str, Any]],
    *,
    phase: str,
    attempt: int,
    error: str,
    diagnosis: str,
    files: list[str],
) -> list[dict[str, Any]]:
    next_turns = list(turns)
    next_turns.append(
        {
            "phase": phase,
            "attempt": attempt,
            "error": redact(error)[:1500],
            "diagnosis": diagnosis[:1500],
            "files": files,
        }
    )
    return next_turns[-MAX_TURNS:]
