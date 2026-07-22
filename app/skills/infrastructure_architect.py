"""Skill: design accurate, dependency-aware cloud infrastructure changes."""
from app.skills.base import Skill


class InfrastructureArchitectSkill(Skill):
    name = "infrastructure_architect"
    category = "Infrastructure & cloud delivery"
    description = (
        "Design or review multi-resource Azure, AWS, or GitHub infrastructure "
        "requests as an ordered, provider-aware implementation plan. Preserve "
        "every requested resource, dependency, region, and configuration detail."
    )
    triggers = [
        "design my Azure infrastructure",
        "plan a VNet with subnets and network security",
        "create an infrastructure deployment plan",
        "review the dependencies in this cloud setup",
    ]
    parameters = {
        "type": "object",
        "properties": {
            "objective": {
                "type": "string",
                "description": "The infrastructure request or design objective.",
            },
            "provider": {
                "type": "string",
                "description": "Target provider when known: Azure, AWS, or GitHub.",
            },
            "constraints": {
                "type": "string",
                "description": "Regions, naming, networking, security, or rollout constraints.",
            },
        },
        "required": ["objective"],
    }
    wiki = (
        "## Infrastructure Architect\n\n"
        "Turns cloud infrastructure requests into complete, dependency-aware "
        "implementation plans. It preserves every resource in a compound request "
        "and identifies the exact inputs still required before execution.\n\n"
        "### What it covers\n"
        "- Azure resource groups, networks, subnets, NSGs, identities and workloads.\n"
        "- AWS networking, IAM, compute, storage and deployment dependencies.\n"
        "- GitHub repository, branch, workflow and release relationships.\n\n"
        "### Safety boundary\n"
        "It does not claim that infrastructure changed. State-changing requests "
        "are converted by the action controller into validated provider CLI "
        "operations with preflight, approval and postcondition verification."
    )
    system_prompt = (
        "You are a principal cloud infrastructure architect. Analyze the user's "
        "complete infrastructure request, including all clauses from the current "
        "turn and same-chat context. Never silently drop a requested resource or "
        "replace it with a generic resource-group-only answer.\n\n"
        "METHOD:\n"
        "1. Extract provider, project scope, region, names, resource types, "
        "configuration, and requested access level.\n"
        "2. Build an ordered dependency graph. Parent scopes such as subscriptions, "
        "resource groups, VPCs/VNets and repositories must precede child resources.\n"
        "3. Separate read preflight, write operation, and post-write verification "
        "for every state-changing resource.\n"
        "4. Preserve exact values already supplied in the conversation. Ask only "
        "for values that are genuinely required and absent.\n"
        "5. If the request is complete, provide a structured ordered plan suitable "
        "for conversion into az, aws, or gh argument arrays. Do not invent names, "
        "regions, address spaces, images, repositories, or subscriptions.\n\n"
        "OUTPUT (Markdown):\n"
        "- Intent and provider scope.\n"
        "- Ordered resources and dependencies.\n"
        "- Per-resource preflight, change, verification, risk, and recovery boundary.\n"
        "- Missing inputs, if any.\n"
        "- Explicit note that no change has been executed.\n\n"
        "For a live write request, do not claim success and do not substitute a "
        "plain-text shell script for the structured action controller."
    )


skill = InfrastructureArchitectSkill()
