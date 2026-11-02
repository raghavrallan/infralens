"""Thin module actuators — propose PRs / gated changes; never silent prod apply."""
from __future__ import annotations

import uuid
from typing import Any, Optional

from app.platform import memory
from app.core.rbac import assert_capability, can, has_min_role


def _proposal(
    *,
    module: str,
    title: str,
    action_class: str,
    gate: str,
    blast_radius: str,
    rollback: str,
    expected_result: str,
    evidence: list[str],
    pr: Optional[dict[str, Any]] = None,
    degrade_plan: str = "",
    why: str = "",
) -> dict[str, Any]:
    return {
        "id": str(uuid.uuid4()),
        "module": module,
        "title": title,
        "action_class": action_class,
        "gate": gate,
        "blast_radius": blast_radius,
        "rollback": rollback,
        "expected_result": expected_result,
        "evidence": evidence,
        "why": why or title,
        "degrade_plan": degrade_plan or "Revert PR / undo change; monitor dashboards.",
        "pr": pr,
        "executed": False,
        "silent_apply": False,
    }


def pipeline_fix_pr(finding: dict[str, Any], user: dict[str, Any]) -> dict[str, Any]:
    assert_capability(user, "propose_write")
    repo = (finding.get("resource") or "owner/repo").split("@")[0]
    return _proposal(
        module="pipeline_intelligence",
        title=f"Pipeline fix PR for {finding.get('title', 'finding')}",
        action_class="config_code_change",
        gate="human_approval",
        blast_radius=str(finding.get("blast_radius") or "medium"),
        rollback="Revert the PR and re-run the prior green workflow.",
        expected_result="CI workflow passes with the proposed pipeline fix.",
        evidence=[str(finding.get("evidence") or finding.get("title") or "")],
        why="Address pipeline failure/flake from module finding.",
        pr={
            "repo": repo,
            "title": f"fix(ci): {finding.get('title', 'pipeline')[:80]}",
            "body": finding.get("recommended_action") or finding.get("evidence") or "",
            "files": [".github/workflows/ci.yml"],
            "status": "proposed",
        },
    )


def security_patch_pr(finding: dict[str, Any], user: dict[str, Any]) -> dict[str, Any]:
    assert_capability(user, "propose_write")
    repo = (finding.get("resource") or "owner/repo").split("@")[0]
    prod_merge = has_min_role(user.get("role"), "devops_lead")
    return _proposal(
        module="security_patch",
        title=f"Security patch PR for {finding.get('title', 'vuln')}",
        action_class="config_code_change",
        gate="two_person" if not prod_merge else "human_approval",
        blast_radius=str(finding.get("blast_radius") or "high"),
        rollback="Revert dependency bump PR; redeploy previous artifact.",
        expected_result="Vulnerability remediated; scanners clear on path.",
        evidence=[str(finding.get("evidence") or "")],
        why="Patch from Security & Patch module finding.",
        pr={
            "repo": repo,
            "title": f"fix(security): {finding.get('title', 'patch')[:80]}",
            "body": finding.get("recommended_action") or "",
            "files": ["requirements.txt", "package.json"],
            "status": "proposed",
            "prod_merge_requires": "devops_lead",
        },
    )


def iac_plan_or_apply(
    *,
    mode: str,
    finding: dict[str, Any],
    user: dict[str, Any],
    environment: str = "dev",
) -> dict[str, Any]:
    mode = (mode or "plan").lower()
    if mode == "plan":
        # Autonomous plan is free for Developer+.
        if not can(user, "propose_write"):
            assert_capability(user, "propose_write")
        return _proposal(
            module="iac",
            title="IaC plan (autonomous)",
            action_class="read_diagnose",
            gate="autonomous_logged",
            blast_radius="low",
            rollback="N/A — plan only",
            expected_result="Terraform plan / drift report attached as ActionDiff",
            evidence=[str(finding.get("evidence") or "drift scan")],
            why="IaC plan is autonomous; apply remains gated.",
        )
    if mode == "apply":
        if environment == "prod" and not has_min_role(user.get("role"), "devops_lead"):
            from fastapi import HTTPException

            raise HTTPException(status_code=403, detail="Prod IaC apply requires DevOps Lead+")
        assert_capability(user, "propose_write")
        return _proposal(
            module="iac",
            title="IaC apply (gated)",
            action_class="irreversible_high_blast" if environment == "prod" else "reversible_change",
            gate="two_person" if environment == "prod" else "human_approval",
            blast_radius="high" if environment == "prod" else "medium",
            rollback="terraform apply previous state / restore from backup",
            expected_result="Infrastructure matches desired state",
            evidence=[str(finding.get("evidence") or "")],
            why="Gated apply — never silent.",
        )
    if mode == "delete":
        assert_capability(user, "approve_two_person")
        return _proposal(
            module="iac",
            title="IaC delete (two-person)",
            action_class="irreversible_high_blast",
            gate="two_person",
            blast_radius="high",
            rollback="Recreate from Terraform / backup",
            expected_result="Target resources removed after dual approval",
            evidence=[str(finding.get("evidence") or "")],
            why="Deletes always require two-person rule.",
        )
    raise ValueError("mode must be plan, apply, or delete")


def finops_action(
    *,
    mode: str,
    finding: dict[str, Any],
    user: dict[str, Any],
) -> dict[str, Any]:
    mode = (mode or "recommend").lower()
    if mode == "recommend":
        return _proposal(
            module="finops",
            title="FinOps recommendation (free)",
            action_class="read_diagnose",
            gate="autonomous",
            blast_radius="low",
            rollback="N/A",
            expected_result="Rightsizing / waste recommendation recorded",
            evidence=[str(finding.get("evidence") or finding.get("title") or "")],
            why="Recommendations are free / autonomous.",
        )
    assert_capability(user, "propose_write")
    return _proposal(
        module="finops",
        title=f"FinOps {mode} (gated)",
        action_class="reversible_change",
        gate="human_approval",
        blast_radius="medium",
        rollback="Resize/start previous SKU; undo stop",
        expected_result=f"Resource {mode} completed safely",
        evidence=[str(finding.get("evidence") or "")],
        why="Resize/stop changes are gated.",
    )


def release_promote(finding: dict[str, Any], user: dict[str, Any]) -> dict[str, Any]:
    assert_capability(user, "propose_write")
    score = 72
    evidence = finding.get("evidence") or ""
    if "green" in str(evidence).lower() or "healthy" in str(evidence).lower():
        score = 88
    return {
        **_proposal(
            module="release_confidence",
            title="Release promote proposal",
            action_class="config_code_change",
            gate="human_approval",
            blast_radius=str(finding.get("blast_radius") or "medium"),
            rollback="Redeploy previous release artifact / roll back slot swap",
            expected_result="Promotion proposal recorded; not auto-executed",
            evidence=[str(evidence)],
            why="Release confidence promote is a proposal only.",
        ),
        "confidence_score": score,
        "promote": {"status": "proposed", "target_env": "staging"},
    }


def incident_runbook(
    *,
    tier: str,
    finding: dict[str, Any],
    user: dict[str, Any],
) -> dict[str, Any]:
    tier = (tier or "diagnose").lower()
    if tier == "diagnose":
        return _proposal(
            module="incident_response",
            title="Incident diagnose (autonomous)",
            action_class="read_diagnose",
            gate="autonomous",
            blast_radius="low",
            rollback="N/A",
            expected_result="Diagnosis and likely cause attached",
            evidence=[str(finding.get("evidence") or "")],
            why="Diagnose tier is free.",
        )
    if tier == "mitigate":
        assert_capability(user, "propose_write")
        return _proposal(
            module="incident_response",
            title="Incident mitigate (safety-direction)",
            action_class="safety_direction",
            gate="autonomous",
            blast_radius="medium",
            rollback="Undo isolation / restore traffic when stable",
            expected_result="Bleeding stopped; service degraded safely",
            evidence=[str(finding.get("evidence") or "")],
            degrade_plan="Keep mitigate in place until root cause PR lands.",
            why="Safety-direction never gated.",
        )
    assert_capability(user, "approve_human")
    return _proposal(
        module="incident_response",
        title="Incident invasive change (gated)",
        action_class="irreversible_high_blast",
        gate="human_approval",
        blast_radius="high",
        rollback="Restore from last known good config",
        expected_result="Invasive fix applied under approval",
        evidence=[str(finding.get("evidence") or "")],
        why="Invasive incident actions remain gated.",
    )


def actuate(
    module: str,
    *,
    user: dict[str, Any],
    finding: Optional[dict[str, Any]] = None,
    mode: str = "",
    tier: str = "",
    environment: str = "dev",
) -> dict[str, Any]:
    finding = finding or {}
    if module == "pipeline_intelligence":
        proposal = pipeline_fix_pr(finding, user)
    elif module == "security_patch":
        proposal = security_patch_pr(finding, user)
    elif module == "iac":
        proposal = iac_plan_or_apply(
            mode=mode or "plan", finding=finding, user=user, environment=environment
        )
    elif module == "finops":
        proposal = finops_action(mode=mode or "recommend", finding=finding, user=user)
    elif module == "release_confidence":
        proposal = release_promote(finding, user)
    elif module == "incident_response":
        proposal = incident_runbook(tier=tier or "diagnose", finding=finding, user=user)
    else:
        raise ValueError(f"Unknown module: {module}")

    memory.remember_action(
        project_id=str(finding.get("project_id") or "default"),
        action_id=proposal["id"],
        summary=proposal["title"],
        outcome="proposed",
        payload={
            "module": module,
            "gate": proposal.get("gate"),
            "blast_radius": proposal.get("blast_radius"),
            "rollback": proposal.get("rollback"),
        },
    )
    return proposal
