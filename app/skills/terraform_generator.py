"""Skill: generate production-grade Terraform for fresh or existing projects."""
from app.skills.base import Skill


class TerraformGeneratorSkill(Skill):
    name = "terraform_generator"
    category = "Infrastructure & cloud delivery"
    description = (
        "Generate production-grade Terraform (main.tf, variables.tf, outputs.tf, "
        "providers.tf, backend.tf and modules) for Azure or AWS from user "
        "requirements and existing project topology. Ready for plan/apply."
    )
    triggers = [
        "generate terraform",
        "create terraform for my infra",
        "write tf code for a vnet and aks",
        "produce infrastructure as code",
    ]
    parameters = {
        "type": "object",
        "properties": {
            "objective": {
                "type": "string",
                "description": "What infrastructure to create, update, or remove.",
            },
            "provider": {
                "type": "string",
                "description": "Target cloud: azure or aws when known.",
            },
            "constraints": {
                "type": "string",
                "description": "Regions, naming, networking, security, or state backend constraints.",
            },
            "existing_state": {
                "type": "string",
                "description": "Existing Terraform/IaC or live inventory to extend safely.",
            },
        },
        "required": ["objective"],
    }
    system_prompt = (
        "You are a principal Terraform engineer. Generate accurate, production-grade "
        "Terraform HCL for the user's request. Use PROJECT TOPOLOGY, live inventory, "
        "and conversation requirements when present. Never invent subscription IDs, "
        "account IDs, regions, address spaces, or resource names that are not supplied "
        "or clearly derived from naming conventions the user already established.\n\n"
        "METHOD:\n"
        "1. Determine fresh vs existing project. For existing projects, extend or "
        "reference discovered modules/state instead of duplicating resources.\n"
        "2. Prefer reusable modules and explicit dependencies (depends_on / references).\n"
        "3. Include tagging, least-privilege identity, private networking defaults, "
        "and remote-state backend placeholders when appropriate.\n"
        "4. For deletes/updates, call out blast radius and a rollback strategy "
        "(previous state / targeted destroy / recreate path).\n"
        "5. Emit complete file contents in fenced code blocks with filenames.\n\n"
        "OUTPUT (Markdown):\n"
        "- Intent and target provider/environment\n"
        "- File tree\n"
        "- Full HCL for each file\n"
        "- Variables the user must still supply\n"
        "- Suggested next step: terraform init → validate → plan → apply via "
        "terraform_executor\n"
        "- Explicit note that nothing has been applied yet"
    )


skill = TerraformGeneratorSkill()
