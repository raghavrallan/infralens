"""Skill: agentic solution architect (HLD, ADRs, gated findings)."""
from typing import Any, Iterator

from app.agents.solution_architect.graph import stream_architect
from app.skills.base import AgenticSkill, SkillResult


class SolutionArchitectSkill(AgenticSkill):
    name = "solution_architect"
    category = "Infrastructure & cloud delivery"
    description = (
        "Clarify, explore the live estate, design against a quality-attribute "
        "rubric, critique and senior-verify, then hand off an HLD with ADRs. "
        "Use for architecture tickets — not Auto mode."
    )
    triggers = [
        "design the architecture",
        "solution architect",
        "add a job queue to my API",
        "multi-region order platform",
        "write an ADR",
    ]
    parameters = {
        "type": "object",
        "properties": {
            "objective": {
                "type": "string",
                "description": "Architecture ask or requirements brief.",
            },
            "constraints": {
                "type": "string",
                "description": "Compliance, region, team, or budget constraints.",
            },
        },
        "required": ["objective"],
    }
    wiki = (
        "## Solution Architect\n\n"
        "An agentic architect that sizes the ticket (T1–T3), explores connected "
        "providers, designs against the same six concern areas as Intelligence "
        "modules, critiques with the Risk Engine, and records ADRs as gated "
        "findings in the existing Approvals inbox.\n\n"
        "Force it with `/solution_architect` in Agent or Plan mode. It is not "
        "auto-routed and cannot be attached to a scheduled workflow."
    )

    def stream_events(self, args: dict[str, Any], *, chat_id: str = "") -> Iterator[dict[str, Any]]:
        yield from stream_architect(args, chat_id=chat_id)

    def run(self, args: dict[str, Any]) -> SkillResult:
        return super().run(args)


skill = SolutionArchitectSkill()
