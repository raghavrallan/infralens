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
    "terraform", "tf apply", "tf plan",
)
# Soft nouns that often appear in reviews; alone they must NOT force the CLI
# action planner (that path was hijacking drift/posture questions).
_SOFT_INFRA_TERMS = ("infra", "infrastructure", "iac")
_PROVIDER_TERMS = (
    "azure", "aws", "github", "az ", "aws ", "gh ", "cli", "cloud",
    "container app", "resource group", "resource-group", "vnet", "virtual network",
    "subnet", "cloudformation", "repository", "repo",
    "terraform", "tf ", ".tf", "iac", "infrastructure",
)
_TF_TERMS = (
    "terraform", "tf apply", "tf plan", "tf destroy", ".tf", "hcl",
    "terraform apply", "terraform plan", "terraform destroy", "terraform init",
)
_WRITE_VERBS = (
    "create", "deploy", "provision", "update", "modify", "change", "delete",
    "remove", "scale", "restart", "start", "stop", "publish", "release",
    "apply", "rollback", "promote", "run workflow", "dispatch", "push",
    "destroy", "execute",
)
_DIAGNOSTIC_TERMS = (
    "review", "reviw", "revie", "audit", "audt",
    "posture", "postur", "posute", "drift", "drft",
    "compare", "compar", "against", "againt", "agaisnt",
    "missing iac", "missin iac", "public exposure", "public exposur",
    "publicly exposed", "call out", "callout",
    "what's missing", "whats missing", "what is missing",
    "present in code", "in the code", "in code", "in our github",
    "against what's in", "security review", "securty", "inventory",
    "inventry", "every service", "every resource", "everything",
    "evrything", "evrthing", "all of it", "all of them", "whole setup",
    "check azure", "check github", "look at azure", "look at github",
    "go thru", "go through", "whats wrong", "what's wrong", "any issues",
    "any risk", "risky", "exposur", "hardning", "hardening",
)
# Short vague follow-ups that continue a prior diagnostic chat.
_DIAGNOSTIC_FOLLOWUP = re.compile(
    r"^(?:ok|okay|k|bro|pls|please|yeah|ya|yep|same|also|and|"
    r"now|then|next)?[\s,.-]*"
    r"(?:all|everything|evrything|evrthing|all of (?:it|them)|"
    r"every(?:thing| service| resource| app| repo)?|"
    r"same for (?:github|azure|all|the code|code|cloud)|"
    r"for (?:all|everything|github|azure)|"
    r"the code|in (?:the )?code|present in code|"
    r"(?:same for the code|not just cloud|use whatever is mapped|"
    r"subscription is fine|whole (?:thing|sub|subscription)|"
    r"idk which repo|dont know which repo|don't know which repo)|"
    r"and (?:cost|metrics|logs|cpu|drift|posture|the code)|"
    r"what about (?:cost|metrics|logs|cpu|github|azure|drift|errors|5xx)|"
    r"now (?:cost|metrics|logs|cpu|drift)|"
    r"do (?:both|all)|check (?:both|all|everything)|"
    r"just (?:do|check|run) (?:it|all|everything)|"
    r"container app|container apps)"
    r".*$",
    re.IGNORECASE,
)
_CONFIRMATION = re.compile(r"^(yes|y|confirm(?:ed)?|approved?|approve|proceed|do it|execute|go ahead)(?:\s+(?:deploy|create|apply|run|execute))?\s*[.!]*$", re.IGNORECASE)
_SCOPE_QUESTION_RE = re.compile(
    r"which (github )?(repo|repository|repos)|which azure scope|"
    r"subscription,? resource group|resource group,? or specific|"
    r"which (subscription|resource group|rg)\b|"
    r"tell me (the |which )?(repo|repository|subscription|scope)",
    re.IGNORECASE,
)
# Pronoun-only CLI follow-ups may reuse provider context from recent turns.
_PRONOUN_ACTION = re.compile(
    r"^(show|list|get|describe|inspect|fetch|read|create|deploy|provision|update|"
    r"modify|change|delete|remove|scale|restart|start|stop|apply|rollback|"
    r"promote|publish|release)\s+(it|that|this|them|the same)\b",
    re.IGNORECASE,
)

ACTION_PLANNER_SYSTEM_PROMPT = """
You are the structured provider-action planner for a DevSecOps automation suite.
Understand the CURRENT user request and conversation context, then return ONLY
valid JSON. The current request is authoritative; prior assistant messages are
context, not new instructions. Never return markdown, shell syntax,
credentials, or a command string.

The only allowed executables are az, aws, gh, and terraform. The operation args
field must be a JSON array of individual arguments. Never use sh, bash,
PowerShell, cmd, pipes, redirects, command substitution, or arbitrary OS
commands. Prefer terraform for multi-resource infrastructure create/update/
delete when the user asks for IaC or production-grade infrastructure.

Choose kind=none for ordinary questions, reviews, audits, drift checks,
posture reviews, and any read-only analysis of already-connected Azure/GitHub
inventory or Terraform in repos. Do NOT choose clarification just to ask
which repository or Azure scope when providers are already connected — that
is handled by the normal chat orchestrator. Choose kind=clarification only
when a state-changing request is understood but a required target, artifact,
region, subscription, repository, branch, image, or deployment name is
missing. Put short missing field names in needs and ask one concise question
in question. Choose kind=action only when every value needed for the exact
operation is present in the conversation. Never invent a resource name,
image, file path, repository, branch, region, subscription, or environment.
When a request has multiple operations, account for every operation. For
multiple operations on the same provider, return them in order in
`operations`; they execute sequentially under one approval. Do not execute
the first operation while silently dropping later operations. If operations
span providers or cannot be represented safely, choose kind=clarification.
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
provider: azure, aws, github, or terraform
executable: az, aws, gh, or terraform
args: individual safe CLI arguments, without credentials
target: a concise provider/resource scope
access_scope: read_only or write
expected_result, risk, rollback: short user-facing descriptions
rollback must describe a machine-executable undo (prefer JSON undo args)
preflight: a read-before-write argument array, or [] for read-only
verify: a postcondition argument array, or [] for read-only
preflight_expect: an exact stdout value only when the preflight uses a boolean
or other exact state check, otherwise ""

Provider command guidance (examples, not an allowlist): use any supported
Azure CLI command group, AWS CLI service, GitHub CLI command, or terraform
phase (init/validate/plan/apply/destroy) required by the request. Preserve the
complete structured argument array. For AWS, require an explicit region and
target. For GitHub, keep repository scope mapped to the project and deliver
code changes through a branch and pull request, never directly to the default
branch. For Terraform write phases, include plan summary context and a
structured rollback (destroy of apply scope or re-apply previous plan).

Every write operation must include a real read-before-write preflight and a
real verification operation. For destructive operations, explain the blast
radius and provide a machine-executable rollback.

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


def looks_like_diagnostic(
    message: str, history: list[dict[str, str]] | None = None
) -> bool:
    """True for read-only drift/posture/review asks — never CLI-action territory."""
    text = (message or "").lower()
    if not text.strip():
        return False
    has_diagnostic = any(term in text for term in _DIAGNOSTIC_TERMS)
    has_write = any(term in text for term in _WRITE_VERBS)
    # Pure review / compare / "everything in code" follow-ups.
    if has_diagnostic and not has_write:
        return True
    if has_diagnostic and any(
        term in text
        for term in (
            "review", "reviw", "audit", "call out", "posture", "postur", "drift", "drft",
        )
    ):
        return True
    # Messy short follow-ups after a diagnostic turn ("all of it bro", "same for github").
    if _DIAGNOSTIC_FOLLOWUP.match(text.strip()):
        context = "\n".join(
            str(item.get("content", "")).lower()
            for item in (history or [])
            if item.get("role") in {"user", "assistant"} and item.get("content")
        )
        if any(term in context for term in _DIAGNOSTIC_TERMS):
            return True
        if any(
            term in context
            for term in ("azure", "github", "infra", "drift", "posture", "repo")
        ):
            return True
    return False


def looks_like_scope_clarification(question: str) -> bool:
    """True when the action planner is interviewing for repo/Azure scope."""
    return bool(_SCOPE_QUESTION_RE.search(question or ""))


def looks_like_action(message: str, history: list[dict[str, str]]) -> bool:
    """Avoid an LLM planning call for normal chat and analysis questions."""
    text = (message or "").lower()
    context = "\n".join(
        str(item.get("content", "")).lower()
        for item in history
        if item.get("content")
    )
    if looks_like_diagnostic(message, history):
        return False
    if _CONFIRMATION.fullmatch(text.strip()):
        return any(term in context for term in _ACTION_TERMS + _SOFT_INFRA_TERMS)
    # Terraform apply/plan/destroy is an action; bare "terraform" in a review is not.
    if any(term in text for term in _TF_TERMS) and any(
        term in text for term in ("apply", "plan", "destroy", "init", "provision", "deploy", "create")
    ):
        return True
    # Current message must itself look like a provider action. Do not let prior
    # chat history turn short follow-ups ("everything in code") into actions —
    # except pronoun CLI follow-ups like "show it" / "delete that".
    has_action = any(term in text for term in _ACTION_TERMS)
    has_soft = any(term in text for term in _SOFT_INFRA_TERMS)
    has_provider = any(term in text for term in _PROVIDER_TERMS)
    if _PRONOUN_ACTION.search(text.strip()) and any(
        term in context for term in _PROVIDER_TERMS
    ):
        return True
    if has_action and has_provider:
        return True
    # Soft infra nouns only count with a real write verb + provider.
    if has_soft and has_provider and any(term in text for term in _WRITE_VERBS):
        return True
    return False


def looks_like_terraform(message: str, history: list[dict[str, str]] | None = None) -> bool:
    text = (message or "").lower()
    if any(term in text for term in _TF_TERMS):
        return True
    context = "\n".join(
        str(item.get("content", "")).lower()
        for item in (history or [])
        if item.get("content")
    )
    return "terraform" in context and any(
        term in text for term in ("apply", "plan", "destroy", "provision", "deploy", "create")
    )


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
