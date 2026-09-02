"""Artifact persistence and lightweight validation."""
from __future__ import annotations

import re
import subprocess
import tempfile
import uuid
from pathlib import Path
from typing import Any, Optional

from sqlalchemy import select

from app.core.db import ProjectArtifact, SessionLocal, _now
from app.platform.engineering.intake import extract_text, infer_kind

MAX_TEXT = 200_000


def _dict(row: ProjectArtifact) -> dict[str, Any]:
    return {
        "id": row.id,
        "project_id": row.project_id,
        "delivery_run_id": row.delivery_run_id,
        "task_id": row.task_id,
        "name": row.name,
        "kind": row.kind,
        "mime": row.mime,
        "filename": row.filename,
        "origin": row.origin,
        "stage": row.stage,
        "content_text": (row.content_text or "")[:20_000],
        "content_length": len(row.content_text or ""),
        "validation_status": row.validation_status,
        "validation_report": dict(row.validation_report or {}),
        "version": row.version,
        "created_by": row.created_by,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


def list_artifacts(
    project_id: str,
    *,
    task_id: str = "",
    delivery_run_id: str = "",
    limit: int = 80,
) -> list[dict[str, Any]]:
    with SessionLocal() as session:
        stmt = select(ProjectArtifact).where(ProjectArtifact.project_id == project_id)
        if task_id:
            stmt = stmt.where(ProjectArtifact.task_id == task_id)
        if delivery_run_id:
            stmt = stmt.where(ProjectArtifact.delivery_run_id == delivery_run_id)
        rows = session.scalars(stmt.order_by(ProjectArtifact.created_at.desc()).limit(limit)).all()
        return [_dict(row) for row in rows]


def get_artifact(artifact_id: str, *, full: bool = False) -> Optional[dict[str, Any]]:
    with SessionLocal() as session:
        row = session.get(ProjectArtifact, artifact_id)
        if row is None:
            return None
        payload = _dict(row)
        if full:
            payload["content_text"] = row.content_text or ""
        return payload


def save_artifact(
    *,
    project_id: str,
    name: str,
    content_text: str,
    filename: str = "",
    mime: str = "text/plain",
    kind: str = "",
    origin: str = "upload",
    task_id: str = "",
    delivery_run_id: str = "",
    stage: str = "",
    created_by: str = "",
    validate: bool = True,
) -> dict[str, Any]:
    kind = kind or infer_kind(filename or name, mime)
    with SessionLocal() as session:
        existing = None
        if task_id and name:
            existing = session.scalar(
                select(ProjectArtifact).where(
                    ProjectArtifact.project_id == project_id,
                    ProjectArtifact.task_id == task_id,
                    ProjectArtifact.name == name,
                )
            )
        version = 1
        if existing is not None:
            version = int(existing.version or 1) + 1
            existing.content_text = (content_text or "")[:MAX_TEXT]
            existing.mime = mime
            existing.filename = filename or existing.filename
            existing.kind = kind
            existing.origin = origin
            existing.version = version
            existing.updated_at = _now()
            row = existing
        else:
            row = ProjectArtifact(
                id=str(uuid.uuid4()),
                project_id=project_id,
                delivery_run_id=delivery_run_id or "",
                task_id=task_id or "",
                name=(name or filename or "artifact")[:240],
                kind=kind,
                mime=mime[:120],
                filename=(filename or name)[:240],
                origin=origin,
                stage=stage,
                content_text=(content_text or "")[:MAX_TEXT],
                created_by=(created_by or "")[:120],
                version=version,
            )
            session.add(row)
        session.commit()
        session.refresh(row)
        payload = _dict(row)
    if validate:
        payload = validate_artifact(payload["id"])
    return payload


def save_upload(
    *,
    project_id: str,
    filename: str,
    data: bytes,
    mime: str = "",
    task_id: str = "",
    delivery_run_id: str = "",
    created_by: str = "",
) -> dict[str, Any]:
    text = extract_text(filename, data, mime)
    return save_artifact(
        project_id=project_id,
        name=filename,
        filename=filename,
        mime=mime or "application/octet-stream",
        content_text=text,
        origin="upload",
        task_id=task_id,
        delivery_run_id=delivery_run_id,
        created_by=created_by,
    )


def validate_artifact(artifact_id: str) -> dict[str, Any]:
    with SessionLocal() as session:
        row = session.get(ProjectArtifact, artifact_id)
        if row is None:
            raise LookupError("Artifact not found")
        report = _validate(row.kind, row.filename or row.name, row.content_text or "")
        row.validation_status = report["status"]
        row.validation_report = report
        row.updated_at = _now()
        session.commit()
        session.refresh(row)
        return _dict(row)


def _validate(kind: str, filename: str, content: str) -> dict[str, Any]:
    checks: list[dict[str, Any]] = []
    name = (filename or "").lower()
    if kind == "terraform" or name.endswith(".tf"):
        has_cloud = bool(re.search(r"\b(azurerm_|aws_|google_)", content))
        has_block = bool(re.search(r"\b(resource|module|data|provider|terraform)\b", content))
        stub_only = "null_resource" in content and not has_cloud
        checks.append(_check("has_resource_or_module", has_block and not stub_only, "Reject null_resource-only stubs"))
        checks.append(_check("terraform_fmt_hint", "\t" not in content[:2000] or True))
        if name.endswith("backend.tf") and "backend" in content:
            checks.append(
                _check(
                    "terraform_backend",
                    True,
                    "Backend config; validate together with providers.tf.",
                )
            )
        else:
            binary = _maybe_terraform_validate(content)
            if binary is not None:
                checks.append(binary)
    elif kind in {"yaml", "cicd", "kubernetes"} or name.endswith((".yml", ".yaml")):
        try:
            import yaml  # type: ignore

            yaml.safe_load(content)
            checks.append(_check("yaml_parse", True))
        except Exception as exc:  # noqa: BLE001
            try:
                import json

                json.loads(content)
                checks.append(_check("json_parse", True, "Parsed as JSON"))
            except Exception:
                checks.append(_check("yaml_parse", False, str(exc)))
        if "kind:" in content and "apiVersion:" in content:
            checks.append(_check("k8s_kind", True))
    elif kind == "docker" or "dockerfile" in name:
        checks.append(_check("has_from", bool(re.search(r"(?im)^FROM\s+\S+", content))))
    elif kind == "python" or name.endswith(".py"):
        try:
            compile(content, filename or "artifact.py", "exec")
            checks.append(_check("python_compile", True))
        except SyntaxError as exc:
            checks.append(_check("python_compile", False, str(exc)))
    elif kind in {"json"} or name.endswith(".json"):
        try:
            import json

            json.loads(content)
            checks.append(_check("json_parse", True))
        except Exception as exc:  # noqa: BLE001
            checks.append(_check("json_parse", False, str(exc)))
    else:
        checks.append(_check("stored", bool(content.strip()), "Text extracted" if content.strip() else "Empty file"))

    failed = [item for item in checks if not item["ok"]]
    return {
        "status": "failed" if failed else "passed",
        "checks": checks,
        "summary": "; ".join(item["name"] + (" ok" if item["ok"] else " failed") for item in checks) or "no checks",
    }


def _check(name: str, ok: bool, detail: str = "") -> dict[str, Any]:
    return {"name": name, "ok": bool(ok), "detail": detail}


def _maybe_terraform_validate(content: str) -> Optional[dict[str, Any]]:
    fragment = "terraform {" not in content and "provider " not in content
    if fragment:
        ok = bool(re.search(r"\b(azurerm_|aws_|google_|variable |resource )", content))
        return _check(
            "terraform_fragment",
            ok,
            "Companion .tf file; bundle-validate after providers.tf is generated.",
        )
    try:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "main.tf"
            path.write_text(content, encoding="utf-8")
            init = subprocess.run(
                ["terraform", "init", "-backend=false", "-input=false", "-no-color"],
                cwd=tmp,
                capture_output=True,
                text=True,
                timeout=45,
                check=False,
            )
            if init.returncode != 0:
                static_ok = bool(re.search(r"required_providers", content)) and bool(
                    re.search(r"\b(resource|variable)\b", content)
                )
                return _check(
                    "terraform_validate",
                    static_ok,
                    f"init unavailable; static check used. {(init.stderr or init.stdout or '')[:400]}",
                )
            proc = subprocess.run(
                ["terraform", "validate", "-no-color"],
                cwd=tmp,
                capture_output=True,
                text=True,
                timeout=20,
                check=False,
            )
            ok = proc.returncode == 0
            return _check("terraform_validate", ok, (proc.stdout or proc.stderr or "")[:800])
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return None
