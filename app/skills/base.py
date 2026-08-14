"""Skill framework: base class, result type, and a global registry.

A *skill* is a reusable, self-contained DevSecOps capability. Each skill owns:
  - metadata (name, description, example triggers, category)
  - a specialised system prompt encoding its domain expertise
  - a JSON-schema of parameters it needs (used for LLM tool-calling)
  - a run() method that performs one focused LLM call and returns a result

The orchestrator exposes every registered skill to the model as a callable
tool, so the model can pick the right skill for a user's request.
"""
from dataclasses import dataclass, field
from typing import Any, Iterator, Optional

from app import azure_client


@dataclass
class SkillResult:
    """Structured output returned by a skill run."""

    skill: str
    content: str
    metadata: dict[str, Any] = field(default_factory=dict)


class Skill:
    """Base class for all DevSecOps skills.

    Subclasses set the class-level metadata attributes and typically only need
    to rely on the default run() implementation, which performs a single
    system-prompted completion over the provided inputs.
    """

    name: str = ""
    category: str = "general"
    description: str = ""
    triggers: list[str] = []
    # Long-form Markdown documentation shown on the skill's wiki page.
    wiki: str = ""
    system_prompt: str = ""
    parameters: dict[str, Any] = {
        "type": "object",
        "properties": {
            "input": {
                "type": "string",
                "description": "The primary artifact or request text to process.",
            }
        },
        "required": ["input"],
    }
    # Ask the model for JSON output when a skill emits structured findings.
    json_output: bool = False
    temperature: float = 0.2
    # Agentic skills run a graph instead of one completion. Keep them out of
    # Auto-mode planning unless auto_routable is explicitly True.
    is_agentic: bool = False
    auto_routable: bool = True

    def build_user_prompt(self, args: dict[str, Any]) -> str:
        """Render tool-call arguments into a single user prompt.

        Skills with richer schemas can override this for custom formatting.
        """
        parts: list[str] = []
        for key, value in args.items():
            label = key.replace("_", " ").title()
            parts.append(f"### {label}\n{value}")
        return "\n\n".join(parts) if parts else "(no input provided)"

    def build_messages(self, args: dict[str, Any]) -> list[dict[str, Any]]:
        """Build the system + user messages for this skill run."""
        from app.prompts import get_text_prompt

        system = get_text_prompt(
            f"skill-{self.name}",
            fallback=self.system_prompt,
        )
        return [
            {"role": "system", "content": system},
            {"role": "user", "content": self.build_user_prompt(args)},
        ]

    def run(self, args: dict[str, Any]) -> SkillResult:
        """Execute the skill via one focused Azure OpenAI completion."""
        from app import observability

        messages = self.build_messages(args)
        response_format = {"type": "json_object"} if self.json_output else None
        with observability.tracing_context(
            feature="skill",
            tags=["skill", self.name],
            generation_name=f"skill-{self.name}",
        ):
            completion = azure_client.chat(
                messages=messages,
                temperature=self.temperature,
                response_format=response_format,
                name=f"skill-{self.name}",
            )
        content = completion.choices[0].message.content or ""
        return SkillResult(
            skill=self.name,
            content=content,
            metadata={"category": self.category},
        )

    def stream_events(self, args: dict[str, Any], *, chat_id: str = "") -> Any:
        """Yield orchestrator events: {type: status|delta|final, ...}.

        Default implementation runs once and yields the full reply as a delta.
        Agentic skills override this to stream graph progress.
        """
        result = self.run(args)
        if result.content:
            yield {"type": "delta", "text": result.content}
        yield {
            "type": "final",
            "mode": "agent",
            "reply": result.content,
            "skills_used": [self.name],
        }

    def as_tool(self) -> dict[str, Any]:
        """Return the OpenAI tool definition for this skill."""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }


class AgenticSkill(Skill):
    """Skill backed by an interruptible multi-node graph rather than one LLM call."""

    is_agentic = True
    auto_routable = False

    def run(self, args: dict[str, Any]) -> SkillResult:
        chunks: list[str] = []
        final: dict[str, Any] = {}
        thread_id = str(args.get("chat_id") or args.get("thread_id") or "")
        for event in self.stream_events(args, chat_id=thread_id):
            if event.get("type") == "delta":
                chunks.append(str(event.get("text") or ""))
            if event.get("type") == "final":
                final = event
        content = str(final.get("reply") or "".join(chunks))
        return SkillResult(skill=self.name, content=content, metadata=final)

    def stream_events(self, args: dict[str, Any], *, chat_id: str = "") -> Any:
        raise NotImplementedError(f"{self.name} must implement stream_events")


class SkillRegistry:
    """Holds all available skills and exposes lookup / tool export helpers."""

    def __init__(self) -> None:
        self._skills: dict[str, Skill] = {}

    def register(self, skill: Skill) -> Skill:
        if not skill.name:
            raise ValueError("Skill must define a non-empty name.")
        if skill.name in self._skills:
            raise ValueError(f"Duplicate skill name: {skill.name}")
        self._skills[skill.name] = skill
        return skill

    def get(self, name: str) -> Optional[Skill]:
        return self._skills.get(name)

    def all(self) -> list[Skill]:
        return list(self._skills.values())

    def tools(self) -> list[dict[str, Any]]:
        return [skill.as_tool() for skill in self._skills.values()]


registry = SkillRegistry()
