"""Skill: diagnose failed infra/deploy actions and propose bounded fixes."""
from app.skills.base import Skill


class InfraDebuggerSkill(Skill):
    name = "infra_debugger"
    category = "Observability & response"
    description = (
        "Diagnose failed Terraform applies, CLI provisioners, and pipeline deploys. "
        "Propose a concrete fix and a bounded retry through the approval-gated path."
    )
    triggers = [
        "fix the failed deploy",
        "why did terraform apply fail",
        "debug the infrastructure error",
        "retry after the build failed",
    ]
    parameters = {
        "type": "object",
        "properties": {
            "objective": {
                "type": "string",
                "description": "What failed and what outcome is desired.",
            },
            "error_output": {
                "type": "string",
                "description": "CLI/TF/pipeline error evidence when available.",
            },
            "attempted_change": {
                "type": "string",
                "description": "What was attempted before the failure.",
            },
        },
        "required": ["objective"],
    }
    wiki = (
        "## Infra Debugger\n\n"
        "Uses failure evidence to propose a fix, then routes retries through the "
        "same approval and rollback controls as the original change."
    )
    system_prompt = (
        "You are a senior infrastructure debugger. Use the failure evidence, project "
        "topology, recent deployment outcomes, and attempted change to find the root "
        "cause and a safe fix.\n\n"
        "METHOD:\n"
        "1. Restate the failure with the exact error signals.\n"
        "2. Identify most likely root cause and alternatives.\n"
        "3. Propose a minimal fix (HCL/CLI args/config).\n"
        "4. Define a bounded retry (max attempts, backoff) and rollback if retry fails.\n"
        "5. Never invent credentials or bypass approval gates.\n\n"
        "OUTPUT (Markdown):\n"
        "- Root cause\n"
        "- Evidence\n"
        "- Fix\n"
        "- Retry plan\n"
        "- Rollback plan"
    )


skill = InfraDebuggerSkill()
