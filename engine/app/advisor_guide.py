"""Advisor remediation text.

The console playbook is the default. This module asks the configured Azure
OpenAI deployment for steps, and it answers an Advisor handoff in chat without
crawling the estate. It never runs Azure CLI.
"""

from __future__ import annotations

import json
import re
from typing import Any

from app.core import azure_client, config
from app.core.azure_client import AzureOpenAINotConfiguredError

MARKER = "ADVISOR_GUIDE"
_SHELL = re.compile(r"[;&|`$<>]|&&|\|\|")
_DENIED = re.compile(
    r"role assignment|ad sp|account clear|logout|login|group delete|subscription delete|rest --method delete",
    re.I,
)


def configured() -> bool:
    return bool(config.get_azure_config().configured)


def clean_command(value: str) -> str:
    line = " ".join(str(value or "").split())
    if not line.lower().startswith("az "):
        return ""
    if len(line) > 180 or _SHELL.search(line) or _DENIED.search(line):
        return ""
    return line


def clean_steps(values: Any) -> list[str]:
    if not isinstance(values, list):
        return []
    steps = []
    for item in values:
        text = " ".join(str(item or "").split())
        if text and len(text) <= 240:
            steps.append(text)
        if len(steps) == 6:
            break
    return steps


def _parse_guide(raw: str) -> dict[str, Any]:
    try:
        payload = json.loads(raw or "{}")
    except json.JSONDecodeError:
        return {}
    if not isinstance(payload, dict):
        return {}
    steps = clean_steps(payload.get("steps"))
    commands = [line for line in (clean_command(item) for item in payload.get("commands") or []) if line][:4]
    caution = " ".join(str(payload.get("caution") or "").split())[:240]
    if not steps:
        return {}
    return {"steps": steps, "commands": commands, "caution": caution}


def enrich_one(item: dict[str, Any]) -> dict[str, Any] | None:
    """Ask the configured model for one recommendation. None means keep the playbook."""
    if not configured():
        return None
    problem = " ".join(str(item.get("problem") or "").split())[:400]
    solution = " ".join(str(item.get("solution") or "").split())[:400]
    if not problem:
        return None
    messages = [
        {
            "role": "system",
            "content": (
                "You write remediation guidance for one Azure Advisor recommendation. "
                "Return JSON with keys steps, commands, and caution. "
                "steps is up to 6 short imperative sentences. "
                "commands is up to 4 az CLI lines that only read data, each starting with az. "
                "Do not assign roles, delete subscriptions, print secrets, or claim the change was applied."
            ),
        },
        {
            "role": "user",
            "content": (
                f"Category: {item.get('category') or 'Advisor'}\n"
                f"Impact: {item.get('impact') or 'Unspecified'}\n"
                f"Recommendation: {problem}\n"
                f"Azure solution: {solution or 'None supplied.'}"
            ),
        },
    ]
    try:
        completion = azure_client.chat(
            messages,
            temperature=0.1,
            response_format={"type": "json_object"},
            name="advisor-guide",
        )
        content = completion.choices[0].message.content or ""
    except (AzureOpenAINotConfiguredError, AttributeError, IndexError, TypeError, ValueError):
        return None
    except Exception:
        return None
    guide = _parse_guide(content)
    if not guide:
        return None
    guide["id"] = str(item.get("id") or "")
    guide["source"] = "model"
    return guide


def reply_for_handoff(text: str) -> str | None:
    """Guide an Advisor chat turn. None when this message is not a handoff."""
    body = str(text or "").lstrip()
    if not body.startswith(MARKER):
        return None
    detail = body[len(MARKER) :].strip()
    if not configured():
        return (
            "No AI model is configured, so this stays on the playbook in your message. "
            "Follow those numbered steps. The az lines only list Advisor recommendations. "
            "I will not change Azure unless you explicitly ask me to apply one command, and a write still needs your approval in chat."
        )
    messages = [
        {
            "role": "system",
            "content": (
                "You are guiding one Azure Advisor recommendation inside Infralens chat. "
                "Explain the risk and the fix in plain sentences. "
                "Repeat only read-only az commands. "
                "Do not say you changed Azure. Tell the user a write happens only after they ask to apply one command and approve it."
            ),
        },
        {"role": "user", "content": detail[:4000] or "Explain this Advisor recommendation."},
    ]
    try:
        completion = azure_client.chat(messages, temperature=0.2, name="advisor-handoff")
        reply = (completion.choices[0].message.content or "").strip()
    except Exception:
        reply = ""
    if reply:
        return reply[:4000]
    return (
        "I could not reach the model. Use the numbered steps in your message. "
        "Ask me to apply one command when you want a change, then approve it in chat."
    )
