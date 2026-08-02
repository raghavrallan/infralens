"""Skill: end-to-end deployment orchestration with canary and health checks."""
from app.skills.base import Skill


class DeploymentManagerSkill(Skill):
    name = "deployment_manager"
    category = "Delivery & supply-chain controls"
    description = (
        "Orchestrate end-to-end deployments: validate → plan → apply → verify → "
        "health-check, with optional canary rollout and automatic rollback triggers."
    )
    triggers = [
        "deploy to production",
        "roll out a canary",
        "run the full deployment pipeline",
        "promote this release",
    ]
    parameters = {
        "type": "object",
        "properties": {
            "objective": {
                "type": "string",
                "description": "What to deploy and to which environment.",
            },
            "strategy": {
                "type": "string",
                "description": "all_at_once|canary|blue_green when known.",
            },
            "constraints": {
                "type": "string",
                "description": "SLO, health checks, traffic percentage, freeze windows.",
            },
        },
        "required": ["objective"],
    }
    wiki = (
        "## Deployment Manager\n\n"
        "Plans governed rollouts that include verification and rollback triggers. "
        "Actual changes still go through the execution control plane."
    )
    system_prompt = (
        "You are a release and deployment orchestrator. Build a concrete, ordered "
        "deployment plan grounded in project topology and existing pipelines.\n\n"
        "Always include:\n"
        "1. Preconditions / lint / validate\n"
        "2. Plan / diff\n"
        "3. Approval boundary\n"
        "4. Apply / promote\n"
        "5. Postcondition verification and health checks\n"
        "6. Canary slice when requested or when production blast radius is high\n"
        "7. Automatic rollback trigger criteria\n\n"
        "Do not claim a live deploy happened without executor confirmation. Prefer "
        "Terraform for infra and existing CI/CD for app artifacts when present."
    )


skill = DeploymentManagerSkill()
