"""Run read-only chat scenarios against the local API (one chat each)."""
from __future__ import annotations

import json
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx

BASE = "http://127.0.0.1:8000"
PROJECT_ID = "5310f26d-911a-47f6-b7ab-4376d8ab78bd"
USERNAME = "admin"
PASSWORD = "infralens"
TIMEOUT_S = 240.0
WORKERS = 2

SCOPE_BUG_RE = re.compile(
    r"which (github )?(repo|repository)|which azure scope|"
    r"subscription,? resource group|resource group,? or specific",
    re.IGNORECASE,
)

SCENARIOS: list[dict[str, str]] = [
    {
        "id": "01",
        "skill": "cloud_posture",
        "question": (
            "Review our connected Azure and GitHub security posture. Call out "
            "risky public exposure, open management ports, and hardening gaps."
        ),
    },
    {
        "id": "02",
        "skill": "drift_auditor",
        "question": (
            "Compare live Azure infrastructure against what's declared or "
            "deployed from our GitHub repos. Report drift and missing IaC."
        ),
    },
    {
        "id": "03",
        "skill": "iac_reviewer",
        "question": (
            "Review the Terraform, Bicep, Dockerfile, and Kubernetes manifests "
            "in our mapped GitHub repos for security and reliability issues."
        ),
    },
    {
        "id": "04",
        "skill": "pipeline_auditor",
        "question": (
            "Audit our CI/CD pipelines (GitHub Actions and Azure Pipelines YAML) "
            "for secrets exposure, weak approvals, and missing security gates."
        ),
    },
    {
        "id": "05",
        "skill": "pipeline_generator",
        "question": (
            "Propose a hardened CI/CD pipeline for eqip_backend with build, "
            "scan, and deploy stages. Recommend only — do not change anything."
        ),
    },
    {
        "id": "06",
        "skill": "code_reviewer",
        "question": (
            "Review application source in Sarai-Platforms-LLC/eqip_backend for "
            "security and reliability issues. Use the connected GitHub repos."
        ),
    },
    {
        "id": "07",
        "skill": "cost_analyzer",
        "question": (
            "What is our current Azure spend and top cost drivers in the "
            "connected subscription?"
        ),
    },
    {
        "id": "08",
        "skill": "metrics_analyzer",
        "question": (
            "Show CPU and memory metrics for all Container Apps over the last "
            "24 hours."
        ),
    },
    {
        "id": "09",
        "skill": "log_analyzer",
        "question": (
            "Are there elevated 4xx or 5xx request errors for our Azure apps "
            "in the last 24 hours?"
        ),
    },
    {
        "id": "10",
        "skill": "vuln_triage",
        "question": (
            "Triage security vulnerabilities and Dependabot-style findings "
            "across our connected GitHub repositories."
        ),
    },
    {
        "id": "11",
        "skill": "compliance_mapper",
        "question": (
            "Map our current Azure and GitHub controls to a practical CIS-style "
            "baseline and list the biggest compliance gaps."
        ),
    },
    {
        "id": "12",
        "skill": "incident_analyzer",
        "question": (
            "Using live inventory and recent telemetry, analyze likely causes "
            "if a Container App revision becomes unhealthy or fails to start."
        ),
    },
    {
        "id": "13",
        "skill": "infrastructure_architect",
        "question": (
            "Design a secure multi-tier Azure architecture for EQIP that fits "
            "our existing repos and current environment. Recommendations only."
        ),
    },
    {
        "id": "14",
        "skill": "terraform_generator",
        "question": (
            "Propose Terraform for an Azure Container App backed by ACR that "
            "matches our EQIP style. Do not apply — show the proposed modules "
            "and a rollback idea."
        ),
    },
    {
        "id": "15",
        "skill": "terraform_executor",
        "question": (
            "Explain a safe terraform plan/apply workflow for our existing "
            "IaC in GitHub, including preflight checks and rollback. Read-only "
            "guidance only."
        ),
    },
    {
        "id": "16",
        "skill": "infra_debugger",
        "question": (
            "Help debug a typical Azure Container Apps deploy failure from "
            "pipeline logs — image pull, revision not healthy, or ACR auth. "
            "Use our live environment context."
        ),
    },
    {
        "id": "17",
        "skill": "deployment_manager",
        "question": (
            "Outline a read-only canary / rollout plan for deploying "
            "eqip_frontend to Azure Static Web Apps with verification and "
            "rollback steps."
        ),
    },
    {
        "id": "18",
        "skill": "project_analyzer",
        "question": (
            "Analyze the overall EQIP project: mapped repos, app structure, "
            "IaC presence, and how frontend/backend/devops fit together."
        ),
    },
    {
        "id": "19",
        "skill": "report_writer",
        "question": (
            "Write a short executive service report summarizing EQIP Azure "
            "posture, drift risk, and top 5 recommended actions."
        ),
    },
    {
        "id": "20",
        "skill": "policy_generator",
        "question": (
            "Recommend least-privilege Azure Policy / guardrails we should "
            "apply for public storage, open NSGs, and required tags. Propose "
            "only — do not apply."
        ),
    },
    {
        "id": "21",
        "skill": "cloud_posture+github",
        "question": (
            "Check our GitHub org/repos for missing branch protection, public "
            "repos that should be private, and secret scanning gaps."
        ),
    },
    {
        "id": "22",
        "skill": "iac_reviewer+docker",
        "question": (
            "Review Dockerfiles in our GitHub repos for insecure base images, "
            "root users, and secret leakage risk."
        ),
    },
    {
        "id": "23",
        "skill": "metrics_analyzer+all",
        "question": (
            "How have our main Azure apps been performing — CPU, memory, and "
            "requests for every matching Container App?"
        ),
    },
    {
        "id": "24",
        "skill": "drift_auditor+services",
        "question": (
            "List every Azure service that exists live but is not represented "
            "by Terraform/Bicep or deploy pipelines in our code."
        ),
    },
    {
        "id": "25",
        "skill": "pipeline_auditor+ado",
        "question": (
            "Review Azure DevOps / azure-pipelines YAML in "
            "Sarai-Platforms-LLC/eqip_devops and related repos for unsafe "
            "deploy practices."
        ),
    },
    {
        "id": "26",
        "skill": "cost_analyzer+savings",
        "question": (
            "Suggest Azure cost savings based on our connected subscription "
            "inventory and billing data — idle or oversized resources first."
        ),
    },
    {
        "id": "27",
        "skill": "vuln_triage+deps",
        "question": (
            "Which dependency or container vulnerabilities should we patch "
            "first for EQIP, and why?"
        ),
    },
    {
        "id": "28",
        "skill": "general",
        "question": (
            "In one paragraph, what connected evidence can you already see "
            "for the EQIP project without me pasting files?"
        ),
    },
]


def login(client: httpx.Client) -> str:
    resp = client.post(
        f"{BASE}/api/auth/login",
        json={"username": USERNAME, "password": PASSWORD},
    )
    resp.raise_for_status()
    return str(resp.json()["token"])


def classify(reply: str, skills_used: list[str]) -> dict[str, Any]:
    text = reply or ""
    scope_bug = bool(SCOPE_BUG_RE.search(text)) and len(text) < 800
    empty = not text.strip()
    status = "fail_scope_loop" if scope_bug else ("fail_empty" if empty else "ok")
    return {
        "status": status,
        "scope_bug": scope_bug,
        "skills_used": skills_used,
        "reply_chars": len(text),
        "reply_preview": text[:400].replace("\n", " "),
    }


def run_one(token: str, scenario: dict[str, str]) -> dict[str, Any]:
    headers = {"Authorization": f"Bearer {token}"}
    started = time.time()
    result: dict[str, Any] = {
        "id": scenario["id"],
        "skill_target": scenario["skill"],
        "question": scenario["question"],
        "chat_id": None,
        "error": None,
        "elapsed_s": 0.0,
    }
    try:
        with httpx.Client(timeout=TIMEOUT_S) as client:
            resp = client.post(
                f"{BASE}/api/chat",
                headers=headers,
                json={
                    "message": scenario["question"],
                    "project_id": PROJECT_ID,
                    "mode": "agent",
                    "action_scope": "read_only",
                    "access_level": "ask_approval",
                },
            )
            elapsed = time.time() - started
            result["elapsed_s"] = round(elapsed, 1)
            if resp.status_code >= 400:
                result["error"] = f"HTTP {resp.status_code}: {resp.text[:500]}"
                result["status"] = "fail_http"
                return result
            body = resp.json()
            result["chat_id"] = body.get("chat_id")
            reply = str(body.get("reply") or "")
            skills = list(body.get("skills_used") or [])
            result.update(classify(reply, skills))
            result["needs_clarification"] = bool(body.get("needs_clarification"))
    except Exception as exc:  # noqa: BLE001
        result["elapsed_s"] = round(time.time() - started, 1)
        result["error"] = str(exc)
        result["status"] = "fail_exception"
    return result


def render_md(results: list[dict[str, Any]], out: Path) -> None:
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    ok = sum(1 for r in results if r.get("status") == "ok")
    lines = [
        "# EQIP chat scenario pack (read-only)",
        "",
        f"Generated: {now}",
        f"Project: EQIP (`{PROJECT_ID}`)",
        "Mode: Agent · Actions: Read-only · Access: Ask for approval",
        f"User: `{USERNAME}`",
        "",
        f"## Summary: {ok}/{len(results)} scenarios returned a usable answer",
        "",
        "| # | Target skill | Status | Skills used | Seconds | Chat id |",
        "|---|--------------|--------|-------------|---------|---------|",
    ]
    for r in results:
        skills = ", ".join(r.get("skills_used") or []) or "—"
        chat = r.get("chat_id") or "—"
        lines.append(
            f"| {r['id']} | `{r['skill_target']}` | `{r.get('status', '?')}` | "
            f"{skills} | {r.get('elapsed_s', '?')} | `{chat}` |"
        )
    lines += [
        "",
        "## Questions (copy/paste into separate chats)",
        "",
        "Use one new chat per question. Keep **Read-only actions** selected.",
        "",
    ]
    for r in results:
        lines += [
            f"### {r['id']}. `{r['skill_target']}`",
            "",
            r["question"],
            "",
        ]
        if r.get("status"):
            lines += [
                f"- **Result:** `{r.get('status')}`",
                f"- **Skills used:** {', '.join(r.get('skills_used') or []) or '—'}",
            ]
            if r.get("error"):
                lines.append(f"- **Error:** {r['error']}")
            if r.get("reply_preview"):
                lines.append(f"- **Reply preview:** {r['reply_preview']}")
            lines.append("")
    lines += [
        "## Notes",
        "",
        "- Failures tagged `fail_scope_loop` mean the old bug (asking which repo / Azure scope).",
        "- Write-shaped skills were exercised as **propose / outline / explain** under read-only.",
        "- Full JSON results: `scripts/chat_scenario_results.json`",
        "",
    ]
    out.write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    results_path = root / "scripts" / "chat_scenario_results.json"
    md_path = root / "docs" / "eqip-chat-scenario-questions.md"
    md_path.parent.mkdir(parents=True, exist_ok=True)

    with httpx.Client(timeout=30.0) as client:
        token = login(client)

    # Write questions immediately so the md exists even if a run is interrupted.
    render_md(
        [
            {
                "id": s["id"],
                "skill_target": s["skill"],
                "question": s["question"],
            }
            for s in SCENARIOS
        ],
        md_path,
    )
    print(f"Wrote question pack -> {md_path}", flush=True)

    results: list[dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        futures = {pool.submit(run_one, token, s): s for s in SCENARIOS}
        for fut in as_completed(futures):
            item = fut.result()
            results.append(item)
            print(
                f"[{item['id']}] {item.get('status')} "
                f"skills={item.get('skills_used')} "
                f"{item.get('elapsed_s')}s",
                flush=True,
            )

    results.sort(key=lambda r: r["id"])
    results_path.write_text(json.dumps(results, indent=2), encoding="utf-8")
    render_md(results, md_path)
    ok = sum(1 for r in results if r.get("status") == "ok")
    print(f"Done: {ok}/{len(results)} ok -> {md_path}", flush=True)


if __name__ == "__main__":
    main()
