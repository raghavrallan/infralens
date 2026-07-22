"""LLM-assisted intent extraction for provider CLI actions.

The model may identify an operation and missing inputs, but it never returns a
shell command to execute. The returned argument array is validated again by
``app.execution.validation`` before it can become an action job.
"""
import json
import re
from typing import Any, Optional

from app import azure_client

_ACTION_TERMS = (
    "create", "deploy", "provision", "update", "modify", "change", "delete",
    "remove", "scale", "restart", "start", "stop", "publish", "release",
    "apply", "rollback", "promote", "run workflow", "dispatch", "push",
    "show", "list", "get", "describe", "inspect", "fetch", "read",
)
_PROVIDER_TERMS = (
    "azure", "aws", "github", "az ", "aws ", "gh ", "cli", "cloud",
    "container app", "resource group", "resource-group", "vnet", "virtual network",
    "subnet", "cloudformation", "repository", "repo",
)
_CONFIRMATION = re.compile(r"^(yes|y|confirm(?:ed)?|approved?|approve|proceed|do it|execute|go ahead)(?:\s+(?:deploy|create|apply|run|execute))?\s*[.!]*$", re.IGNORECASE)

ACTION_PLANNER_SYSTEM_PROMPT = """
You are the structured provider-action planner for a DevSecOps automation suite.
Understand the CURRENT user request and conversation context, then return ONLY
valid JSON. The current request is authoritative; prior assistant messages are
context, not new instructions. Never return markdown, shell syntax,
credentials, or a command string.

The only allowed executables are az, aws, and gh. The operation args field must
be a JSON array of individual arguments. Never use sh, bash, PowerShell, cmd,
pipes, redirects, command substitution, or arbitrary OS commands.

Choose kind=none for ordinary questions. Choose kind=clarification when a
state-changing request is understood but a required target, artifact, region,
subscription, repository, branch, image, or deployment name is missing. Put
short missing field names in needs and ask one concise question in question.
Choose kind=action only when every value needed for the exact operation is
present in the conversation. Never invent a resource name, image, file path,
repository, branch, region, subscription, or environment. When a request has
multiple operations, account for every operation. For multiple operations on
the same provider, return them in order in `operations`; they execute
sequentially under one approval. Do not execute the first operation while
silently dropping later operations. If operations span providers or cannot be
represented safely, choose kind=clarification.
When the user says "this", "it", "the same", "confirmed", or gives a short
follow-up, resolve it from the compact same-chat memory and the latest action
target. Do not ask for a value that is already present there. Preserve the
previous provider, resource, region, repository, metric, and time range unless
the user explicitly changes it. A new request containing a concrete resource,
service, operation, or artifact is NOT approval for a previous pending action.
Never repeat the previous command just because both turns contain words such
as create, deploy, or provision. If the current request asks for a child
resource, use that resource's native CLI operation and include the parent as
an ordered dependency only when it is actually required. If a current request
contains several resources, represent every requested operation in order; do
not silently return only the first resource.

For an action, return operation with:
provider: azure, aws, or github
executable: az, aws, or gh
args: individual safe CLI arguments, without credentials
target: a concise provider/resource scope
access_scope: read_only or write
expected_result, risk, rollback: short user-facing descriptions
preflight: a read-before-write argument array, or [] for read-only
verify: a postcondition argument array, or [] for read-only
preflight_expect: an exact stdout value only when the preflight uses a boolean
or other exact state check, otherwise ""

Provider command guidance (examples, not an allowlist): use any supported
Azure CLI command group, AWS CLI service, or GitHub CLI command required by the
request. Preserve the complete structured argument array. For AWS, require an
explicit region and target. For GitHub, keep repository scope mapped to the
project and deliver code changes through a branch and pull request, never
directly to the default branch. For every provider, use the provider's native
read-before-write and postcondition commands.

Every write operation must include a real read-before-write preflight and a
real verification operation. For destructive operations, explain the blast
radius and do not invent a rollback command.

JSON schema:
{
  "kind": "none|clarification|action",
  "question": "",
  "needs": [],
  "operation": {
    "provider": "",
    "executable": "",
    "args": [],
    "target": "",
    "access_scope": "read_only|write",
    "expected_result": "",
    "risk": "",
    "rollback": "",
    "preflight": [],
    "preflight_expect": "",
    "verify": []
  },
  "operations": []
}
""".strip()


def looks_like_action(message: str, history: list[dict[str, str]]) -> bool:
    """Avoid an LLM planning call for normal chat and analysis questions."""
    text = (message or "").lower()
    context = "\n".join(
        str(item.get("content", "")).lower()
        for item in history
        if item.get("content")
    )
    if _CONFIRMATION.fullmatch(text.strip()):
        return any(term in context for term in _ACTION_TERMS)
    has_action = any(term in text for term in _ACTION_TERMS) or any(
        term in context for term in _ACTION_TERMS
    )
    has_provider = any(term in text for term in _PROVIDER_TERMS) or any(
        term in context for term in _PROVIDER_TERMS
    )
    return has_action and has_provider


def plan_action(
    message: str,
    history: list[dict[str, str]],
    provider_context: str,
) -> Optional[dict[str, Any]]:
    """Extract a structured action intent or return None for normal chat."""
    if not looks_like_action(message, history):
        return None
    memory = [
        {"role": "system", "content": item.get("content", "")[:10000]}
        for item in history
        if item.get("role") == "system"
        and (
            "CHAT MEMORY" in item.get("content", "")
            or "RECENT CHAT TURNS" in item.get("content", "")
        )
    ]
    recent = [
        {"role": item.get("role", "user"), "content": item.get("content", "")[:6000]}
        for item in history[-6:]
        if item.get("role") in {"user", "assistant"}
    ]
    context = memory[-2:] + recent
    prompt = (
        "Project-scoped provider status (secrets are hidden):\n"
        + provider_context
        + "\n\nCURRENT USER REQUEST (authoritative; plan this request, not an earlier command):\n"
        + message[:10000]
        + "\n\nConversation context:\n"
        + json.dumps(context, ensure_ascii=True)
        + "\n\nReturn the JSON action decision now."
    )
    try:
        completion = azure_client.chat(
            [
                {"role": "system", "content": ACTION_PLANNER_SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
            temperature=0,
            response_format={"type": "json_object"},
        )
        content = completion.choices[0].message.content or "{}"
        parsed = json.loads(content)
    except Exception:
        # The normal orchestrator remains the fallback if structured planning
        # is unavailable or the configured model does not support JSON mode.
        return None
    if not isinstance(parsed, dict) or parsed.get("kind") not in {"none", "clarification", "action"}:
        return None
    operation = parsed.get("operation") if isinstance(parsed.get("operation"), dict) else {}
    operations = parsed.get("operations") if isinstance(parsed.get("operations"), list) else []
    operations = [item for item in operations[:16] if isinstance(item, dict)]
    if not operations and operation:
        operations = [operation]
    needs = parsed.get("needs") if isinstance(parsed.get("needs"), list) else []
    return {
        "kind": parsed["kind"],
        "question": str(parsed.get("question") or "").strip()[:2000],
        "needs": [str(item)[:120] for item in needs[:12]],
        "operation": operation,
        "operations": operations,
    }
