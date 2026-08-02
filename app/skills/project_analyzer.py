"""Skill: deep analysis of existing repos, apps, and infrastructure."""
from app.skills.base import Skill


class ProjectAnalyzerSkill(Skill):
    name = "project_analyzer"
    category = "Infrastructure & cloud delivery"
    description = (
        "Deeply analyze an existing project: backend/frontend repos, Terraform/IaC, "
        "CI/CD, environments, and live infrastructure topology to ground next actions."
    )
    triggers = [
        "analyze my project",
        "what do we already have in github and azure",
        "map the existing infrastructure and repos",
        "understand this codebase and infra",
    ]
    parameters = {
        "type": "object",
        "properties": {
            "objective": {
                "type": "string",
                "description": "What the user wants to understand or prepare for.",
            },
            "focus": {
                "type": "string",
                "description": "repos|iac|live_infra|pipelines|all",
            },
        },
        "required": ["objective"],
    }
    wiki = (
        "## Project Analyzer\n\n"
        "Builds a grounded map of an existing project before create/update/delete "
        "operations so the assistant does not act as if the estate is empty."
    )
    system_prompt = (
        "You are a principal engineer performing project discovery. Use PROJECT "
        "TOPOLOGY, live inventory, and repository evidence already provided. Do not "
        "ask the user to paste files that are present in context.\n\n"
        "Produce:\n"
        "1. Project mode confirmation (existing)\n"
        "2. Repository map (BE/FE/infra) with frameworks when evident\n"
        "3. IaC inventory and environments/branches\n"
        "4. Live cloud topology summary\n"
        "5. Gaps / drift / risks\n"
        "6. Recommended next actions (generate TF, fix drift, deploy, debug)\n\n"
        "Be concrete: cite repo paths, resource types, and environments."
    )


skill = ProjectAnalyzerSkill()
