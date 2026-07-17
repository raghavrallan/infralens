"""Skill: compare live cloud infrastructure against the infra-as-code / pipelines."""
from app.skills.base import Skill


class DriftAuditorSkill(Skill):
    name = "drift_auditor"
    category = "Infrastructure & drift"
    description = (
        "Compare the user's LIVE cloud inventory against their infrastructure "
        "code and deployment pipelines to find drift and gaps: resources running "
        "in the cloud that aren't defined in code, things defined in code that "
        "aren't deployed, and missing best-practice configuration. Both the live "
        "Azure inventory and the real repo code (on the right branch) are "
        "provided, so use this for 'understand my infra then compare to my code', "
        "'what's missing in my IaC', 'is my code in sync with what's deployed'."
    )
    triggers = [
        "understand my infra then compare it to my terraform and tell what's missing",
        "is my infrastructure code in sync with what's actually deployed",
        "what resources exist in azure that aren't in my code",
        "compare my deployed environment against my pipelines",
    ]
    parameters = {
        "type": "object",
        "properties": {
            "objective": {
                "type": "string",
                "description": "The infra-vs-code comparison / drift question.",
            }
        },
        "required": ["objective"],
    }
    wiki = (
        "## Infra ↔ Code Drift Auditor\n\n"
        "Compares what's *actually running* in your cloud against what your "
        "infrastructure code and deployment pipelines say should exist — both "
        "pulled live and read-only. Highlights drift, gaps and missing "
        "best-practice configuration.\n\n"
        "### When to use it\n"
        "- 'Understand my infra, then compare it to my Terraform/pipelines and "
        "tell me what's missing.'\n"
        "- 'What's running in Azure that isn't captured in code?'\n"
        "- 'Is my IaC in sync with the deployed environment?'\n\n"
        "### What it uses\n"
        "The Azure connection (for the live inventory) and the GitHub connection "
        "(for the IaC / pipeline code on the resolved environment branch), both "
        "for the active project.\n\n"
        "### What you get back\n"
        "A drift matrix — in cloud only, in code only, in both — plus missing "
        "guardrails and a prioritized reconciliation list. It never changes "
        "anything.\n\n"
        "### Maps to\n"
        "Operating model control point: *Infrastructure as code & configuration "
        "management*."
    )
    system_prompt = (
        "You are a senior platform engineer performing a read-only drift and gap "
        "analysis between a customer's LIVE cloud inventory and their "
        "infrastructure code / deployment pipelines — BOTH provided to you below "
        "(the live Azure inventory and the real repo code on the resolved "
        "branch). Reason ONLY over what is provided; cite exact resource names and "
        "the exact repo/path/branch. Do NOT ask the user to paste anything that is "
        "already provided.\n\n"
        "IMPORTANT: If the repos contain NO declarative IaC (no Terraform/Bicep) "
        "and the environment is instead deployed via pipelines (e.g. Azure DevOps "
        "YAML that runs az/docker commands), say so plainly and base the "
        "comparison on what the pipelines actually deploy versus what is running. "
        "Never invent Terraform that isn't there.\n\n"
        "METHOD:\n"
        "- Enumerate what's deployed (from the live inventory) and what's declared "
        "or deployed by code (from the repos).\n"
        "- Classify each notable resource/config as: in cloud only (undeclared / "
        "possible drift), in code only (declared but not deployed), or in both "
        "(and whether config matches).\n"
        "- Flag missing best-practice guardrails relative to what's deployed "
        "(e.g. no diagnostic settings, public exposure, no autoscale, hardcoded "
        "config that should be parameterised).\n\n"
        "OUTPUT (Markdown):\n"
        "- A one-line verdict on how in-sync code and cloud are.\n"
        "- A drift table: Resource / Concern | In cloud | In code | Notes.\n"
        "- A 'Gaps & what's missing' list, prioritized.\n"
        "- A short reconciliation plan (what to add to code, what to import, what "
        "to remove) — as recommendations only.\n\n"
        "GUARDRAILS — READ-ONLY. Recommend; never present changes as applied and "
        "never output commands to run unless the user explicitly asks."
    )


skill = DriftAuditorSkill()
