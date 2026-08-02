"""Skill: plan and describe Terraform execution via the controlled runner path."""
from app.skills.base import Skill


class TerraformExecutorSkill(Skill):
    name = "terraform_executor"
    category = "Infrastructure & cloud delivery"
    description = (
        "Prepare and describe a Terraform init/validate/plan/apply workflow with "
        "approval gates, plan summary, blast radius, and machine-executable rollback. "
        "Does not bypass the execution control plane."
    )
    triggers = [
        "apply the terraform",
        "run terraform plan",
        "execute terraform apply",
        "provision with terraform",
    ]
    parameters = {
        "type": "object",
        "properties": {
            "objective": {
                "type": "string",
                "description": "What to plan or apply with Terraform.",
            },
            "workspace": {
                "type": "string",
                "description": "Workspace or directory name when known.",
            },
            "phase": {
                "type": "string",
                "description": "init|validate|plan|apply|destroy",
            },
        },
        "required": ["objective"],
    }
    wiki = (
        "## Terraform Executor\n\n"
        "Guides Terraform through init → validate → plan → (approval) → apply "
        "using the project's execution engine. Write phases require rollback plans."
    )
    system_prompt = (
        "You are the Terraform execution controller for a governed DevSecOps platform. "
        "Translate the user's request into a clear execution plan for the "
        "terraform_runner control path.\n\n"
        "RULES:\n"
        "1. Never claim terraform apply succeeded unless an executor result confirms it.\n"
        "2. Always sequence: init → validate → plan → human approval → apply.\n"
        "3. Summarize expected adds/changes/destroys when a plan is available in context.\n"
        "4. Every write/apply/destroy must include a machine-executable rollback "
        "(targeted destroy of created resources, or restore previous state).\n"
        "5. Prefer project topology and generated HCL already in context.\n"
        "6. If HCL is missing, instruct that terraform_generator must run first.\n\n"
        "OUTPUT (Markdown):\n"
        "- Phase sequence\n"
        "- Workspace / provider assumptions\n"
        "- Plan summary (or what will be planned)\n"
        "- Risk, blast radius, rollback operation\n"
        "- Exact next approval-gated action for the control plane"
    )


skill = TerraformExecutorSkill()
