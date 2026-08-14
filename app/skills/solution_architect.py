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

    def stream_events(self, args: dict[str, Any], *, chat_id: str = "") -> Iterator[dict[str, Any]]:
        yield from stream_architect(args, chat_id=chat_id)

    def run(self, args: dict[str, Any]) -> SkillResult:
        return super().run(args)


skill = SolutionArchitectSkill()
