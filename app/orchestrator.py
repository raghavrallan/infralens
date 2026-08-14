"""Chat orchestrator: modes, skill routing, and multi-agent execution.

Two interaction modes:
  - "agent": executes work. If the user forces a skill (dropdown or /command)
    that single skill runs. Otherwise a planner decomposes the task into steps,
    each handled by a separate skill "agent", and the results are synthesised.
  - "plan": read-only. The planner returns the ordered steps it *would* run,
    with rationale, but nothing is executed.

Each step in a task is handled by one skill acting as an independent agent with
its own specialised system prompt (see app/skills/*).
"""
import json
import os
import re
from dataclasses import asdict, dataclass, field
from typing import Any, Iterator, Literal, Optional

from app import azure_client
from app.execution.chat_actions import provider_status_text
from app.providers import aws_infra, azure_infra, github_infra
from app.skills import registry

# Terms that mean "review my whole setup" — trigger every connected provider.
_GENERIC_TRIGGERS = (
    "infrastructure",
    "infra",
    "environment",
    "posture",
    "estate",
    "my cloud",
    "cloud",
    "resources",
    "security review",
    "harden",
    "improve my",
    "drift",
    "public exposure",
    "publicly exposed",
    "missing iac",
    "missing in code",
    "not in code",
    "out of sync",
    "in sync",
)

_PROVIDER_SPECS: tuple[dict[str, Any], ...] = (
    {
        "name": "Azure",
        "label": "AZURE",
        "module": azure_infra,
        "conn_err": azure_infra.AzureConnectionError,
        "api_err": azure_infra.AzureApiError,
        "source": "Azure Resource Graph",
        "advice": (
            "the app registration most likely lacks the 'Reader' role on the "
            "subscription (grant Reader at the subscription scope), or the "
            "subscription id is wrong"
        ),
        "triggers": (
            "azure",
            "subscription",
            "tenant",
            "resource group",
            "nsg",
            "key vault",
            "arm template",
            "bicep",
        ),
    },
    {
        "name": "AWS",
        "label": "AWS",
        "module": aws_infra,
        "conn_err": aws_infra.AwsConnectionError,
        "api_err": aws_infra.AwsApiError,
        "source": "the AWS APIs",
        "advice": (
            "the IAM user/key most likely lacks read permissions (attach a "
            "read-only policy such as SecurityAudit or ReadOnlyAccess), or the "
            "region is wrong"
        ),
        "triggers": (
            "aws",
            "amazon",
            "ec2",
            "s3 bucket",
            "s3",
            "iam",
            "rds",
            "vpc",
            "lambda",
            "cloudformation",
            "security group",
        ),
    },
    {
        "name": "GitHub",
        "label": "GITHUB",
        "module": github_infra,
        "conn_err": github_infra.GitHubConnectionError,
        "api_err": github_infra.GitHubApiError,
        "source": "the GitHub REST API",
        "advice": (
            "the personal access token most likely lacks scope (grant 'repo' "
            "and 'read:org'), or it has expired"
        ),
        "triggers": (
            "github",
            "repo",
            "repository",
            "repositories",
            "branch protection",
            "pull request",
            "workflow",
            "actions",
            "dependabot",
            "secret scanning",
            "organisation",
            "organization",
        ),
    },
)

Mode = Literal["agent", "plan"]
ActionScope = Literal["read_only", "write"]
AccessLevel = Literal["ask_approval", "auto_approve", "full_access"]

_SCOPE_POLICY = {
    "read_only": (
        "OPERATING SCOPE: READ-ONLY. Analyse, review and recommend only. You may "
        "produce example/proposed artifacts, but clearly label anything that "
        "would change live systems as a proposed change — never present it as "
        "already applied or as a command to run without review."
    ),
    "write": (
        "OPERATING SCOPE: WRITE. You may produce concrete, ready-to-apply change "
        "artifacts (pipelines, IaC, policies, commands). Still call out "
        "irreversible or high-blast-radius actions explicitly. For provider "
        "changes, use the structured CLI action path: identify the exact "
        "provider, target, arguments, preflight, postcondition and rollback "
        "boundary. Never claim a live change happened unless an executor result "
        "confirms it."
    ),
}
_ACCESS_POLICY = {
    "ask_approval": (
        "ACCESS: ASK FOR APPROVAL. Before any state-changing action, stop and "
        "ask the user to confirm, summarising exactly what would change."
    ),
    "auto_approve": (
        "ACCESS: AUTO-APPROVE SAFE. Proceed with clearly safe, reversible "
        "actions; pause and ask only for potentially unsafe or irreversible "
        "ones."
    ),
    "full_access": (
        "ACCESS: FULL ACCESS. The user has granted broad authority; still warn "
        "before destructive operations."
    ),
}


def build_policy(action_scope: ActionScope, access_level: AccessLevel) -> str:
    """Compose the operating-policy preamble from the UI controls."""
    scope = _SCOPE_POLICY.get(action_scope, _SCOPE_POLICY["read_only"])
    access = _ACCESS_POLICY.get(access_level, _ACCESS_POLICY["ask_approval"])
    return f"{scope}\n{access}"


def build_agent_policy(action_scope: ActionScope, access_level: AccessLevel) -> str:
    """Add the execution-mode boundary used by chat and approved plan runs."""
    return (
        build_policy(action_scope, access_level)
        + "\nCHAT MODE: AGENT EXECUTION. The requested analysis is running now. Do not "
        "return a plan, an 'Approval checkpoint', or an instruction to approve a "
        "second plan. Report the actual analysis and recommendations; state-changing "
        "actions remain governed by the operating scope and access policy above."
    )


def _provider_block(
    spec: dict[str, Any], force: bool, task_lower: str, project_id: str
) -> Optional[str]:
    """Fetch one provider's live report if it is connected and relevant."""
    module = spec["module"]
    if not module.is_connected(project_id):
        return None
    triggered = (
        force
        or any(k in task_lower for k in spec["triggers"])
        or any(k in task_lower for k in _GENERIC_TRIGGERS)
    )
    if not triggered:
        return None
    try:
        report = module.build_environment_report(project_id)
    except spec["conn_err"]:
        return None
    except spec["api_err"] as exc:
        return (
            f"LIVE {spec['label']} FETCH FAILED. The user's {spec['name']} account "
            "IS connected, but the read-only query failed. Tell the user this, show "
            f"the error verbatim, and note the most likely cause: {spec['advice']}. "
            f"Do NOT ask them to paste files.\nError: {exc}"
        )
    return (
        f"LIVE {spec['label']} ENVIRONMENT DATA — read-only, fetched just now via "
        f"{spec['source']} using the user's connected credentials. Base your analysis "
        "on this REAL data. Do NOT ask the user to paste files, manifests or exports; "
        "you already have their environment below.\n\n" + report["text"]
    )


# Map a user's phrasing to the artifact kinds we should locate in their repos.
_CODE_INTENT: dict[str, tuple[str, ...]] = {
    "terraform": ("terraform", "tfvars", ".tf", " tf ", "hcl"),
    "bicep": ("bicep",),
    "dockerfile": ("dockerfile", "docker file", "containerfile"),
    "kubernetes": ("kubernetes", "k8s", "manifest", "helm chart", "helm"),
    "workflows": (
        "workflow",
        "github actions",
        "actions pipeline",
        "ci pipeline",
        "ci/cd",
        "pipeline",
    ),
    "azure_pipelines": (
        "azure devops",
        "azure-devops",
        "ado",
        "azure pipeline",
        "azure-pipelines",
        "azure pipelines",
        "release pipeline",
        "build pipeline",
        "deploy pipeline",
        "deployment pipeline",
        "pipeline",
        "yaml",
        "yamls",
        "yml",
    ),
    "ansible": ("ansible", "playbook"),
    "source": (
        "source code",
        "my code",
        "the code",
        "code review",
        "review the code",
        "optimize",
        "optimise",
        "optimization",
        "optimisation",
        "refactor",
        "clean up",
        "improve the code",
        "code quality",
        "bug in",
        "why is",
        "function",
        "module",
        "class",
    ),
}
# Generic "look at my whole setup" phrasing → pull the common IaC artifacts too,
# so "review my infra" always considers the real Terraform / Bicep / code.
_INFRA_CODE_TERMS = (
    "infra",
    "infrastructure",
    "my code",
    "review my code",
    "iac",
    "codebase",
    "my repo",
    "my repository",
    "my project",
    "drift",
    "missing iac",
    "missing in code",
    "not in code",
    "out of sync",
    "in sync",
    "exist in the code",
    "exists in the code",
    "defined in code",
    "public exposure",
    "posture",
)
_DIAGNOSTIC_TERMS = (
    "drift",
    "drft",
    "posture",
    "postur",
    "public exposure",
    "public exposur",
    "publicly exposed",
    "missing iac",
    "missin iac",
    "missing in code",
    "not in code",
    "out of sync",
    "in sync",
    "compare azure",
    "compare github",
    "azure vs",
    "vs github",
    "against my code",
    "against github",
    "against the code",
    "exist in the code",
    "exists in the code",
    "present in code",
    "present in the code",
    "every resource",
    "every service",
    "everything",
    "evrything",
    "evrthing",
    "all of it",
    "all of them",
    "whole setup",
    "what resources",
    "inventory",
    "inventry",
    "what's missing",
    "whats missing",
    "what is missing",
    "undeclared",
    "against what's in",
    "risky public",
    "reviw",
    "go thru",
    "go through",
    "any issues",
    "any risk",
    "securty",
    "hardning",
)
_DIAGNOSTIC_FOLLOWUP_RE = re.compile(
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
_REPO_NAME_RE = re.compile(r"\b([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+)\b")
_SCOPE_CLARIFY_RE = re.compile(
    r"which (repo|repository|repos|azure|subscription|resource group|scope|rg)|"
    r"azure scope|subscription vs|resource group vs|"
    r"(repo|repository) (name|to use|should)|"
    r"tell me (the |which )?(repo|repository|subscription|scope)|"
    r"(confirm|specify|provide).{0,40}(repo|subscription|resource group|scope)",
    re.IGNORECASE,
)
_DEFAULT_INFRA_KINDS = (
    "terraform",
    "bicep",
    "kubernetes",
    "dockerfile",
    "azure_pipelines",
)

# Environment keyword patterns (word-boundary) used to pick the right branch.
_ENV_PATTERNS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("prod", (r"\bprod\b", r"\bproduction\b", r"\blive\b", r"\bmaster\b", r"\bmain branch\b")),
    ("uat", (r"\buat\b", r"\buser acceptance\b")),
    ("qa", (r"\bqa\b", r"\bquality assurance\b")),
    ("staging", (r"\bstaging\b", r"\bstage\b", r"\bpre-?prod\b", r"\bpreprod\b")),
    ("dev", (r"\bdevelopment\b", r"\bdevelop\b", r"\bdev\b", r"\bdev env\b")),
)
_BRANCH_STOPWORDS = {
    "the", "a", "an", "this", "that", "my", "which", "env", "environment",
    "default", "same", "right", "correct", "feature", "current", "your", "our",
    "release", "target",
}


def _detect_env(task: str) -> Optional[str]:
    """Resolve which environment the user means, for branch selection."""
    low = task.lower()
    for env, patterns in _ENV_PATTERNS:
        if any(re.search(p, low) for p in patterns):
            return env
    return None


def _detect_branch(task: str) -> Optional[str]:
    """Pick up an explicitly named branch like 'the release/x branch'."""
    low = task.lower()
    match = re.search(r"\bbranch\s+([\w./-]+)", low) or re.search(
        r"\b([\w./-]+)\s+branch\b", low
    )
    if not match:
        return None
    name = match.group(1).strip()
    if name in _BRANCH_STOPWORDS or len(name) < 2:
        return None
    return name

# Beyond this size the user has almost certainly pasted the artifact themselves,
# so don't go fetching code from their repos.
_PASTED_CONTENT_CHARS = 1500


def _detect_code_kinds(task_lower: str) -> list[str]:
    kinds = {
        kind
        for kind, keywords in _CODE_INTENT.items()
        if any(word in task_lower for word in keywords)
    }
    if any(term in task_lower for term in _INFRA_CODE_TERMS):
        kinds.update(_DEFAULT_INFRA_KINDS)
    return list(kinds)


def _extract_named_repos(task: str) -> list[str]:
    """Pull owner/name repo references from the user message."""
    found: list[str] = []
    for match in _REPO_NAME_RE.finditer(task or ""):
        owner, repo = match.group(1), match.group(2)
        if owner.lower() in {"http", "https", "www"}:
            continue
        if repo.lower().endswith(
            (".py", ".md", ".tf", ".yml", ".yaml", ".json", ".txt", ".toml")
        ):
            continue
        full = f"{owner}/{repo}"
        if full.lower() not in {item.lower() for item in found}:
            found.append(full)
    return found


def _looks_like_diagnostic_intent(task: str) -> bool:
    """Read-only drift / posture / inventory asks that must not interview for scope."""
    lowered = (task or "").lower()
    if not lowered:
        return False
    if any(term in lowered for term in _DIAGNOSTIC_TERMS):
        return True
    if _extract_named_repos(task) and any(
        term in lowered for term in ("azure", "github", "infra", "resource", "code", "iac")
    ):
        return True
    # CURRENT USER REQUEST may be a messy follow-up; body still has prior context.
    current = lowered
    if "current user request:" in lowered:
        current = lowered.split("current user request:", 1)[1]
        current = current.split("conversation context:", 1)[0].strip()
    if _DIAGNOSTIC_FOLLOWUP_RE.match(current.strip()):
        return True
    return False


def _looks_like_drift_intent(task: str) -> bool:
    lowered = (task or "").lower()
    drift_terms = (
        "drift",
        "missing iac",
        "missing in code",
        "not in code",
        "out of sync",
        "in sync",
        "against my code",
        "against github",
        "against the code",
        "exist in the code",
        "exists in the code",
        "compare azure",
        "compare github",
        "azure vs",
        "vs github",
        "undeclared",
        "what's missing",
        "what is missing",
    )
    return any(term in lowered for term in drift_terms)


def _looks_like_posture_intent(task: str) -> bool:
    lowered = (task or "").lower()
    return any(
        term in lowered
        for term in (
            "posture",
            "public exposure",
            "publicly exposed",
            "security review",
            "harden",
        )
    )


def _filter_scope_clarifications(
    questions: list[str], live_context: Optional[str], task: str
) -> list[str]:
    """Drop repo/Azure-scope interviews when connections + topology already answer them."""
    live = live_context or ""
    connected_ready = any(
        marker in live
        for marker in (
            "PROJECT TOPOLOGY",
            "ENVIRONMENT DATA",
            "LIVE GITHUB CODE",
            "LIVE AZURE",
            "Provider azure: connected",
            "Provider github: connected",
        )
    )
    if _looks_like_diagnostic_intent(task) and connected_ready:
        return []
    if not connected_ready:
        return questions
    kept = [q for q in questions if not _SCOPE_CLARIFY_RE.search(q)]
    return kept


def _gather_code_context(
    task: str, project_id: str, force: bool = False
) -> Optional[str]:
    """Locate and fetch the real source files the user is asking about from GitHub.

    When ``force`` is set (the planner chose a code-backed skill), fall back to a
    broad default artifact set even if the phrasing matched no specific keyword.
    """
    if len(task) > _PASTED_CONTENT_CHARS or not github_infra.is_connected(project_id):
        return None
    if _looks_like_diagnostic_intent(task):
        force = True
    kinds = _detect_code_kinds(task.lower())
    if not kinds and force:
        kinds = list(_DEFAULT_INFRA_KINDS) + ["source", "workflows"]
    if not kinds:
        return None
    env = _detect_env(task)
    branch = _detect_branch(task)
    prefer_repos = _extract_named_repos(task)
    try:
        report = github_infra.build_code_report(
            project_id,
            kinds,
            env=env,
            branch=branch,
            prefer_repos=prefer_repos or None,
        )
    except github_infra.GitHubConnectionError:
        return None
    except github_infra.GitHubApiError as exc:
        return (
            "LIVE GITHUB CODE FETCH FAILED. The user's GitHub account IS connected, "
            "but reading their repositories failed. Tell the user this, show the "
            "error verbatim, and note the likely cause: the token most likely lacks "
            "scope (grant 'repo' and 'read:org'), or it has expired. Do NOT ask them "
            f"to paste files.\nError: {exc}"
        )
    return report["text"] if report else None


_SECURITY_SKILLS = {"vuln_triage", "compliance_mapper"}
_SECURITY_TASK_TERMS = (
    "vulnerab", "security", "cve", "scanner", "dependabot", "dependency",
    "compliance", "patch", "sbom", "snyk", "trivy", "grype", "codeql",
)
_SECURITY_CONTEXT_MAX_CHARS = 100000


def _is_security_task(task: str) -> bool:
    lowered = (task or "").lower()
    return any(term in lowered for term in _SECURITY_TASK_TERMS)


def _gather_security_context(task: str, project_id: str) -> Optional[str]:
    """Fetch the evidence bundle required by security skills.

    Security triage cannot be grounded by a workflow sentence alone. Gather
    provider posture and repository security artifacts up front, while keeping
    every source read-only and bounded by the provider helpers.
    """
    blocks: list[str] = []
    task_lower = (task or "").lower()

    for spec in _PROVIDER_SPECS:
        block = _provider_block(spec, True, task_lower, project_id)
        if block:
            blocks.append(block)

    if github_infra.is_connected(project_id):
        try:
            report = github_infra.build_code_report(
                project_id,
                ["security", "workflows", "dockerfile"],
                max_files=12,
                max_per_repo=4,
                max_bytes=9000,
                max_repos=15,
                env=_detect_env(task),
                branch=_detect_branch(task),
            )
        except github_infra.GitHubConnectionError:
            report = None
        except github_infra.GitHubApiError as exc:
            report = {
                "text": (
                    "LIVE GITHUB SECURITY ARTIFACTS FETCH FAILED. The GitHub account "
                    "is connected, but repository security evidence could not be "
                    f"read. Error: {exc}"
                )
            }
        if report:
            blocks.append(report["text"])

    if not blocks:
        return (
            "SECURITY EVIDENCE BUNDLE — no connected provider or repository evidence "
            "was available for this project. Do not ask the user to paste data in a "
            "workflow response; report the coverage gap as unknown and state the "
            "read-only source that was unavailable."
        )
    evidence = "\n\n---\n\n".join(blocks)
    if len(evidence) > _SECURITY_CONTEXT_MAX_CHARS:
        evidence = evidence[:_SECURITY_CONTEXT_MAX_CHARS] + (
            "\n\n[Security evidence truncated at the safe context limit. "
            "The listed sources remain read-only and bounded.]"
        )
    return (
        "SECURITY EVIDENCE BUNDLE — gathered read-only just now. Treat the sections "
        "below as the complete evidence available for this run. Distinguish actual "
        "scanner findings from coverage gaps and never invent CVEs, versions, or "
        "control evidence.\n\n" + evidence
    )


# Phrasing that means "tell me what I'm being charged / spending".
_COST_TRIGGERS = (
    "billing",
    "bill",
    "invoice",
    "cost",
    "costs",
    "spend",
    "spending",
    "charge",
    "charges",
    "how much",
    "pricing",
    "expense",
    "expenses",
    "subscription cost",
)


# Billing target keyword -> ServiceName substrings to filter the cost query to.
_COST_SERVICE_FILTERS: tuple[tuple[tuple[str, ...], tuple[str, ...]], ...] = (
    (("storage", "blob", "storage account"), ("storage",)),
    (
        ("foundry", "openai", "open ai", "cognitive", "ai model", "token", "gpt", "llm"),
        ("foundry", "openai", "cognitive", "azure ai"),
    ),
    (("postgres", "postgre", "psql"), ("postgre",)),
    (("container app", "containerapp", "aca"), ("container apps", "app service")),
    (("sql", "sql database"), ("sql",)),
    (("redis", "cache"), ("redis", "cache")),
    (("cosmos",), ("cosmos",)),
    (("app service", "web app"), ("app service",)),
    (("registry", "acr", "container registry"), ("container registry",)),
)
# Phrasing that means "break the bill down finely" (per meter / per token type).
_COST_METER_TERMS = (
    "meter",
    "detail",
    "detailed",
    "breakdown",
    "break down",
    "per model",
    "token",
    "input",
    "output",
    "line item",
)


def _cost_service_filter(task_lower: str) -> Optional[list[str]]:
    for keywords, subs in _COST_SERVICE_FILTERS:
        if any(k in task_lower for k in keywords):
            return list(subs)
    return None


def _gather_cost_context(
    task: str, project_id: str, force: bool = False
) -> Optional[str]:
    """Fetch real Azure spend when the user asks about billing / cost.

    Detects the service the user is asking about (storage, Foundry/OpenAI, …) to
    filter the bill, and whether they want a fine meter-level breakdown (token
    meters for OpenAI, etc.).
    """
    task_lower = task.lower()
    if not force and not any(term in task_lower for term in _COST_TRIGGERS):
        return None
    if not azure_infra.is_connected(project_id):
        return None
    from_date, to_date, label = azure_infra.parse_cost_period(task)
    service_filter = _cost_service_filter(task_lower)
    group_by = "meter" if any(t in task_lower for t in _COST_METER_TERMS) else "service"
    try:
        report = azure_infra.build_cost_report(
            project_id,
            from_date,
            to_date,
            label,
            group_by=group_by,
            service_filter=service_filter,
        )
    except azure_infra.AzureConnectionError:
        return None
    except azure_infra.AzureApiError as exc:
        return (
            "LIVE AZURE BILLING FETCH FAILED. The user's Azure account IS "
            "connected, but the read-only Cost Management query failed. Tell the "
            "user this, show the error verbatim, and note the most likely cause: "
            "the app registration needs the 'Cost Management Reader' role (or "
            "Reader) on the subscription, and a subscription id must be set. Do "
            f"NOT ask them to paste an invoice.\nError: {exc}"
        )
    return (
        "LIVE AZURE BILLING DATA — read-only, fetched just now via Azure Cost "
        "Management using the user's connected credentials. Answer the billing "
        "question directly from these REAL figures. Do NOT ask the user to paste "
        "an invoice or subscription details; the actual spend is below.\n\n"
        + report["text"]
    )


# Phrasing that means "show me telemetry / how busy a resource has been".
_METRIC_TRIGGERS = (
    "metric",
    "metrics",
    "cpu",
    "memory",
    "utilization",
    "utilisation",
    "telemetry",
    "throughput",
    "latency",
    "replicas",
    "how busy",
    "usage over",
    "last 24 hour",
    "last 24 hours",
    "24h",
    "graph of",
    "plot",
    "token",
    "tokens",
    "input token",
    "output token",
    "transactions",
    "connections",
    "iops",
    "requests",
)


_METRIC_INTENT_PROMPT = (
    "From a user's request about cloud resource telemetry, extract which Azure "
    "resource they mean and which metrics they want. Respond ONLY with JSON:\n"
    '{"resource_types": [], "resource_name": null, "metrics": [], "all_resources": false}\n'
    "resource_types: zero or more of exactly these keys — container_app, "
    "postgresql, mysql, mariadb, vm, vmss, sql_database, storage, web_app, aks, "
    "redis, cosmos, app_gateway, service_bus, event_hub, cognitive. Use "
    "'cognitive' for Azure OpenAI / AI Foundry / Cognitive Services / AI models. "
    "Pick the type(s) the user names or that earlier turns named.\n"
    "resource_name: ONLY a concrete Azure resource name (e.g. my-api-ca). "
    "Never put type labels or scope words here: null for container app, app, "
    "all, every, everyone, existing, all of them, which exist.\n"
    "all_resources: true when the user wants every matching resource of that type.\n"
    "metrics: zero or more short keywords — cpu, memory, connections, iops, disk, "
    "storage, requests, latency, network, replicas, restarts, errors, transactions, "
    "tokens, input_tokens, output_tokens, calls. Include every metric they mention. "
    "If they said CPU/memory (or request metrics), include cpu, memory, and requests.\n"
    "The input may include recent chat context. Follow-ups like 'container app', "
    "'all', or 'everyone which exist' MUST resolve from the earlier metrics request. "
    "Never invent a need to ask the user which app when they asked for all or named "
    "only a resource type — leave resource_name null and set all_resources true."
)

_TYPE_FOLLOWUP_KEYWORDS: tuple[tuple[tuple[str, ...], str], ...] = (
    (("container app", "container apps", "aca", "containerapp"), "container_app"),
    (("postgres", "postgresql", "psql"), "postgresql"),
    (("web app", "app service"), "web_app"),
    (("virtual machine", " vm ", "vms"), "vm"),
    (("aks", "kubernetes"), "aks"),
    (("redis",), "redis"),
    (("storage account", "blob"), "storage"),
    (("openai", "foundry", "cognitive"), "cognitive"),
)


def _keyword_metric_scope(
    task: str,
) -> tuple[Optional[list[str]], Optional[str], Optional[list[str]], bool]:
    """Deterministic fallback so short follow-ups still fetch the right metrics."""
    lowered = f" {(task or '').lower()} "
    types: list[str] = []
    for keywords, key in _TYPE_FOLLOWUP_KEYWORDS:
        if any(k in lowered for k in keywords):
            types.append(key)
    all_resources = azure_infra.wants_all_resources(task)
    metrics: list[str] = []
    if "cpu" in lowered:
        metrics.append("cpu")
    if "memory" in lowered or "mem " in lowered:
        metrics.append("memory")
    if "request" in lowered or "throughput" in lowered:
        metrics.append("requests")
    if any(term in lowered for term in ("health", "utilization", "utilisation", "how busy")):
        for hint in ("cpu", "memory", "requests"):
            if hint not in metrics:
                metrics.append(hint)
    return (types or None), None, (metrics or None), all_resources


def _parse_metric_intent(
    task: str,
) -> tuple[Optional[list[str]], Optional[str], Optional[list[str]]]:
    """Resolve resource type(s) and metrics; never treat 'all' as a resource name."""
    kw_types, _kw_name, kw_metrics, kw_all = _keyword_metric_scope(task)
    try:
        completion = azure_client.chat(
            messages=[
                {"role": "system", "content": _METRIC_INTENT_PROMPT},
                {"role": "user", "content": task},
            ],
            temperature=0.0,
            response_format={"type": "json_object"},
        )
        parsed = json.loads(completion.choices[0].message.content or "{}")
    except Exception:  # noqa: BLE001 - fall back to keyword inference on any failure
        types = kw_types or ["container_app"]
        metrics = kw_metrics or ["cpu", "memory"]
        return types, None, metrics
    types = parsed.get("resource_types") or None
    name = parsed.get("resource_name") or None
    metrics = parsed.get("metrics") or None
    all_resources = bool(parsed.get("all_resources")) or kw_all
    types = [t for t in types if isinstance(t, str)] if isinstance(types, list) else None
    metrics = (
        [m for m in metrics if isinstance(m, str)] if isinstance(metrics, list) else None
    )
    if kw_types:
        types = list(dict.fromkeys([*(types or []), *kw_types]))
    if kw_metrics:
        metrics = list(dict.fromkeys([*(metrics or []), *kw_metrics]))
    if all_resources or azure_infra.wants_all_resources(str(name or "")):
        name = None
    if isinstance(name, str) and name.lower() in {
        "all", "every", "everyone", "existing", "container app", "container apps", "app", "apps"
    }:
        name = None
    # Short follow-ups often omit the type in the LLM parse; keep keyword type.
    if not types and kw_types:
        types = kw_types
    if not types and ("main azure app" in (task or "").lower() or "my app" in (task or "").lower()):
        types = ["container_app"]
    return (types or None), (name if isinstance(name, str) else None), (metrics or None)


def _current_request_text(task: str) -> str:
    """Strip conversation wrappers so follow-up detectors see only the latest ask."""
    lowered = (task or "").strip()
    if not lowered:
        return ""
    # _contextual_task wraps as CURRENT USER REQUEST / CONVERSATION CONTEXT.
    marker = "CURRENT USER REQUEST:"
    if marker in lowered:
        body = lowered.split(marker, 1)[1]
        body = re.split(r"\n\s*CONVERSATION CONTEXT:", body, maxsplit=1)[0]
        return body.strip()
    return lowered


def _looks_like_metrics_followup(task: str) -> bool:
    """Short answers that continue a metrics ask (e.g. 'container app', 'all')."""
    lowered = _current_request_text(task).lower().strip()
    if not lowered:
        return False
    # Structural / repo questions must not be treated as metrics follow-ups.
    if any(
        term in lowered
        for term in (
            "backend vs frontend",
            "frontend vs backend",
            "which one is backend",
            "which one is frontend",
            "which repo",
            "rollback",
            "read only",
            "read-only",
            "dependabot",
            "vuln",
            "summarise",
            "summarize",
            "worst 5",
            "executive",
            "acr",
            "image pull",
        )
    ):
        return False
    if any(term in lowered for term in _METRIC_TRIGGERS):
        return True
    if azure_infra.wants_all_resources(lowered):
        return True
    types, _, _, _ = _keyword_metric_scope(lowered)
    return bool(types)


def _prior_turn_was_metrics(messages: list[dict[str, Any]]) -> bool:
    """True when an earlier user turn in this chat was clearly about metrics."""
    for item in messages:
        if item.get("role") != "user":
            continue
        text = str(item.get("content") or "").lower()
        if any(term in text for term in _METRIC_TRIGGERS):
            return True
    return False


def _is_ack_or_policy_nudge(task: str) -> bool:
    """Short turns that should answer directly (no specialist re-run)."""
    lowered = (task or "").lower().strip()
    if not lowered or len(lowered) > 56:
        return False
    return any(
        term in lowered
        for term in (
            "read only",
            "read-only",
            "stick to",
            "dont change",
            "don't change",
            "thanks",
            "thank you",
            "thx",
            "ok thanks",
            "got it",
        )
    )


def _correct_misrouted_steps(
    task: str, steps: list["PlanStep"], messages: list[dict[str, Any]]
) -> list["PlanStep"]:
    """Override clear LLM mis-routes (metrics stealing structural follow-ups)."""
    lowered = (task or "").lower().strip()
    if not lowered:
        return steps
    if _is_ack_or_policy_nudge(task):
        return []
    only_metrics = bool(steps) and all(step.skill == "metrics_analyzer" for step in steps)
    skill_names = {step.skill for step in steps}

    def _one(skill: str, objective: str) -> list[PlanStep]:
        if registry.get(skill) is None:
            return steps
        return [PlanStep(skill=skill, objective=objective)]

    if any(
        term in lowered
        for term in (
            "backend vs frontend",
            "frontend vs backend",
            "which one is backend",
            "which one is frontend",
            "which repo",
            "mapped repo",
        )
    ) and (only_metrics or not steps or skill_names <= {"metrics_analyzer", "drift_auditor"}):
        return _one(
            "project_analyzer",
            "Answer which repos/apps are backend vs frontend from PROJECT TOPOLOGY "
            "and mapped GitHub repos. Do not run metrics.",
        )
    if any(
        term in lowered for term in ("dependabot", "vuln", "vulnerabilit", "cve")
    ) and (
        only_metrics
        or not steps
        or skill_names <= {"metrics_analyzer", "cloud_posture", "drift_auditor"}
    ):
        return _one(
            "vuln_triage",
            "Triage Dependabot / vulnerability coverage for connected GitHub repos.",
        )
    if any(
        term in lowered
        for term in (
            "rollback",
            "if apply failed",
            "apply failed later",
            "tf apply",
            "terraform apply",
        )
    ) and (
        only_metrics
        or skill_names <= {"metrics_analyzer", "drift_auditor", "cloud_posture"}
    ):
        return _one(
            "terraform_executor",
            "Explain a safe Terraform plan/apply/rollback workflow. Read-only guidance.",
        )
    if any(
        term in lowered
        for term in ("acr", "image pull", "pull fail", "revision not healthy")
    ) and (
        only_metrics
        or skill_names <= {"metrics_analyzer", "drift_auditor", "cloud_posture"}
    ):
        return _one(
            "infra_debugger",
            "Explain whether ACR/image-pull is a likely deploy failure cause using live context.",
        )
    if (
        ("worst" in lowered and ("summar" in lowered or "5 thing" in lowered))
        or ("exec report" in lowered)
    ) and (only_metrics or skill_names <= {"metrics_analyzer"}):
        return _one(
            "report_writer",
            "Summarize the worst issues from this conversation's live evidence.",
        )
    # Short type follow-ups only keep metrics when a prior turn was metrics.
    if (
        only_metrics
        and _looks_like_metrics_followup(task)
        and not any(term in lowered for term in _METRIC_TRIGGERS)
        and not _prior_turn_was_metrics(messages)
    ):
        return []
    return steps


def _gather_metrics_context(
    task: str, project_id: str, force: bool = False
) -> tuple[Optional[str], list[dict[str, Any]]]:
    """Fetch real Azure Monitor metrics when the user asks about performance.

    The connected AI parses the request into the resource type(s) and metrics
    involved, so any resource kind (Container App, PostgreSQL, VM, storage, …)
    and any exposed metric (CPU, memory, connections, …) can be fetched.
    Returns a (text_block, charts) pair; ``charts`` is empty when nothing was
    fetched.
    """
    current = _current_request_text(task) or task
    current_lower = current.lower()
    if (
        not force
        and not any(term in current_lower for term in _METRIC_TRIGGERS)
        and not _looks_like_metrics_followup(current)
    ):
        return None, []
    # Follow-ups like "all" / "container app" still need metrics when the prior
    # turn asked for CPU/memory; force discovery rather than asking again.
    if not force and _looks_like_metrics_followup(current):
        force = True
    if not azure_infra.is_connected(project_id):
        return None, []
    resource_types, resource_name, metric_hints = _parse_metric_intent(task)
    if azure_infra.wants_all_resources(current):
        resource_name = None
        if not resource_types:
            resource_types = ["container_app"]
        # Ensure the task text keeps the "all" signal for resource selection.
        task = f"{task}\nScope: all matching resources"
    try:
        report = azure_infra.build_metrics_report(
            project_id,
            task,
            resource_types=resource_types,
            resource_name=resource_name,
            metric_hints=metric_hints,
        )
    except azure_infra.AzureConnectionError:
        return None, []
    except azure_infra.AzureApiError as exc:
        note = (
            "LIVE AZURE METRICS FETCH FAILED. The user's Azure account IS "
            "connected, but the read-only Azure Monitor query failed. Tell the "
            "user this, show the error verbatim, and note the most likely cause: "
            "the app registration needs the 'Monitoring Reader' role (or Reader) "
            "on the subscription, and a subscription id must be set. Do NOT ask "
            f"them to paste telemetry.\nError: {exc}"
        )
        return note, []
    block = (
        "LIVE AZURE METRICS DATA — read-only, fetched just now via Azure Monitor "
        "using the user's connected credentials. Answer the performance question "
        "directly from these REAL figures; the same series is being plotted as a "
        "graph for the user. Do NOT ask the user to paste telemetry.\n\n"
        + report["text"]
    )
    return block, report.get("charts", [])


# Phrasing that means "count errors / HTTP statuses from request telemetry".
_LOG_TRIGGERS = (
    "log",
    "logs",
    "error",
    "errors",
    "4xx",
    "5xx",
    "400",
    "401",
    "403",
    "404",
    "429",
    "500",
    "502",
    "503",
    "504",
    "status code",
    "status codes",
    "failed request",
    "failing",
    "error rate",
)


# Phrasing that means "read the actual log lines / diagnose a failure".
_LOG_CONTENT_TRIGGERS = (
    "log",
    "logs",
    "revision",
    "crash",
    "crashed",
    "restart",
    "exception",
    "traceback",
    "stack trace",
    "stacktrace",
    "failed",
    "failing",
    "failure",
    "provision",
    "deploy",
    "deployment",
    "why is",
    "what happened",
    "root cause",
    "diagnose",
    "not starting",
    "won't start",
)


def _gather_logs_context(
    task: str, project_id: str, force: bool = False
) -> tuple[Optional[str], list[dict[str, Any]]]:
    """Gather live error signals: HTTP status counts and real log/revision content.

    Combines (a) HTTP 4xx/5xx counts from Azure Monitor request telemetry (with a
    chart) and (b) real container app revision status plus system/console log
    lines from Log Analytics, so both "how many 500s" and "why did my revision
    fail — show the logs" are answered from REAL data.
    """
    task_lower = task.lower()
    want_status = force or any(term in task_lower for term in _LOG_TRIGGERS)
    want_content = force or any(term in task_lower for term in _LOG_CONTENT_TRIGGERS)
    if not want_status and not want_content:
        return None, []
    if not azure_infra.is_connected(project_id):
        return None, []

    blocks: list[str] = []
    charts: list[dict[str, Any]] = []

    if want_status:
        try:
            report = azure_infra.build_status_report(project_id, task)
            blocks.append(
                "LIVE AZURE REQUEST/ERROR TELEMETRY — read-only, fetched just now "
                "via Azure Monitor using the user's connected credentials. Answer "
                "the error/status question directly from these REAL counts; 4xx/5xx "
                "are plotted for the user. Do NOT ask the user to paste logs.\n\n"
                + report["text"]
            )
            charts = report.get("charts", [])
        except azure_infra.AzureConnectionError:
            pass
        except azure_infra.AzureApiError as exc:
            blocks.append(
                "LIVE AZURE REQUEST/ERROR TELEMETRY unavailable: the read-only "
                "request-metric query failed or the app had no ingress traffic in "
                f"the window. Error: {exc}"
            )

    if want_content:
        try:
            logs = azure_infra.build_logs_report(project_id, task)
            blocks.append(
                "LIVE AZURE LOGS & REVISION STATUS — read-only, fetched just now "
                "from Log Analytics and the Container Apps control plane. Diagnose "
                "the issue from these REAL revision states and log lines; cite the "
                "revision name/image and the exact log messages. Do NOT ask the "
                "user to paste logs.\n\n" + logs["text"]
            )
        except azure_infra.AzureConnectionError:
            pass
        except azure_infra.AzureApiError as exc:
            blocks.append(
                "LIVE AZURE LOGS FETCH FAILED. The user's Azure account IS "
                "connected, but reading Log Analytics failed. Tell the user this, "
                "show the error verbatim, and note the likely cause: the app "
                "registration needs the 'Log Analytics Reader' (or Reader) role, or "
                "no workspace is linked to the container app environment. Do NOT "
                f"ask them to paste logs.\nError: {exc}"
            )

    if not blocks:
        return None, charts
    return "\n\n---\n\n".join(blocks), charts


def _gather_live_context(
    task: str,
    project_id: str,
    force: bool = False,
    force_cost: bool = False,
    force_metrics: bool = False,
    force_logs: bool = False,
    force_security: bool = False,
) -> tuple[Optional[str], list[dict[str, Any]]]:
    """Fetch live, read-only context from GitHub code and every relevant provider.

    Combines (a) real Azure spend when the user asks about billing/cost, (b) live
    Azure Monitor metrics when they ask about performance/CPU (also returned as
    plottable charts), (c) real source files located in the project's repos when
    they ask about Terraform / Bicep / Dockerfiles / K8s / pipelines / infra, and
    (d) live environment reports for each connected Azure / AWS / GitHub account
    relevant to the request. Everything is scoped to the given project. Returns a
    (combined_text_or_None, charts) pair.
    """
    task_lower = task.lower()
    blocks: list[str] = []
    cost_block = _gather_cost_context(task, project_id, force=force_cost)
    if cost_block:
        blocks.append(cost_block)
    metrics_block, charts = _gather_metrics_context(
        task, project_id, force=force_metrics
    )
    if metrics_block:
        blocks.append(metrics_block)
    logs_block, logs_charts = _gather_logs_context(task, project_id, force=force_logs)
    if logs_block:
        blocks.append(logs_block)
    if logs_charts:
        charts = charts + logs_charts
    diagnostic = _looks_like_diagnostic_intent(task)
    force_env = force or diagnostic
    code_block = _gather_code_context(task, project_id, force=diagnostic)
    if code_block:
        blocks.append(code_block)
    if force_security:
        security_block = _gather_security_context(task, project_id)
        if security_block:
            blocks.append(security_block)
    if not force_security:
        blocks.extend(
            block
            for spec in _PROVIDER_SPECS
            if (block := _provider_block(spec, force_env, task_lower, project_id))
        )
    if diagnostic and azure_infra.is_connected(project_id):
        blocks.insert(
            0,
            "DEFAULT AZURE SCOPE: the connected subscription already configured "
            "for this project. Do NOT ask the user to choose subscription vs "
            "resource group vs resource names — inventory the connected "
            "subscription and compare against the fetched GitHub code.",
        )
    if diagnostic and github_infra.is_connected(project_id):
        named = _extract_named_repos(task)
        repo_note = (
            f" Prefer repository {', '.join(named)} when present in the fetch."
            if named
            else " Use mapped project repositories (and any repo named in the request)."
        )
        blocks.insert(
            0,
            "DEFAULT GITHUB SCOPE: GitHub is already connected."
            + repo_note
            + " Do NOT ask which repository to use.",
        )
    text = "\n\n---\n\n".join(blocks) if blocks else None
    return text, charts


def _ensure_planned_context(
    task: str,
    project_id: str,
    steps: list["PlanStep"],
    live_context: Optional[str],
    charts: list[dict[str, Any]],
) -> tuple[Optional[str], list[dict[str, Any]]]:
    """Guarantee the data-backed skills the planner chose actually have live data.

    Skill routing is decided by the LLM while the keyword gate decides what live
    data we pre-fetch; the two can disagree (e.g. "how has my app been doing"
    routes to metrics_analyzer but matches no metric keyword). When that happens
    the skill would run with no data and no graph, so here we force-fetch the
    data for any data-backed skill the planner selected but we haven't gathered.
    """
    names = {step.skill for step in steps}
    extra: list[str] = []
    if "metrics_analyzer" in names and not charts:
        text, gathered = _gather_metrics_context(task, project_id, force=True)
        if text:
            extra.append(text)
        if gathered:
            charts = gathered
    ctx = live_context or ""
    if names & {"log_analyzer", "incident_analyzer"} and (
        "AZURE REQUEST/ERROR TELEMETRY" not in ctx and "AZURE LOGS" not in ctx
    ):
        text, gathered = _gather_logs_context(task, project_id, force=True)
        if text:
            extra.append(text)
        if gathered:
            charts = charts + gathered
    if "cost_analyzer" in names and "LIVE AZURE BILLING" not in ctx:
        block = _gather_cost_context(task, project_id, force=True)
        if block:
            extra.append(block)
    if names & {"cloud_posture", "drift_auditor"} and "ENVIRONMENT DATA" not in ctx:
        task_lower = task.lower()
        for spec in _PROVIDER_SPECS:
            block = _provider_block(spec, True, task_lower, project_id)
            if block:
                extra.append(block)
    if names & {
        "iac_reviewer",
        "pipeline_auditor",
        "drift_auditor",
        "code_reviewer",
        "incident_analyzer",
        "project_analyzer",
        "terraform_generator",
        "infrastructure_architect",
    } and "LIVE GITHUB CODE" not in ctx:
        code = _gather_code_context(task, project_id, force=True)
        if code:
            extra.append(code)
    if "project_analyzer" in names and "REPOSITORY ANALYSIS" not in ctx:
        try:
            from app.intelligence.repo_analyzer import analyze_to_prompt

            extra.append(analyze_to_prompt(project_id))
        except Exception:  # noqa: BLE001
            pass
    if names & _SECURITY_SKILLS and "SECURITY EVIDENCE BUNDLE" not in ctx:
        security = _gather_security_context(task, project_id)
        if security:
            extra.append(security)
    if extra:
        merged = "\n\n---\n\n".join(extra)
        live_context = (
            merged + "\n\n---\n\n" + live_context if live_context else merged
        )
    return live_context, charts


def _augment_args(args: dict[str, Any], live_context: Optional[str]) -> dict[str, Any]:
    if live_context:
        args = {**args, "live_environment": live_context}
    return args


def _security_framework(text: str) -> str:
    lowered = (text or "").lower()
    if "soc 2" in lowered or "soc2" in lowered:
        return "soc2"
    if "iso 27001" in lowered or "iso27001" in lowered:
        return "iso27001"
    if "pci" in lowered:
        return "pci-dss"
    if "nist" in lowered:
        return "nist-csf"
    return "nist-csf"


def _skill_args(
    skill_name: str,
    task: str,
    objective: str,
    policy: str,
    live_context: Optional[str],
    conversation_context: Optional[str] = None,
) -> dict[str, Any]:
    """Build arguments that match each skill's declared evidence contract."""
    args: dict[str, Any] = {
        "task": task,
        "objective": objective,
        "operating_policy": policy,
    }
    if conversation_context:
        args["conversation_memory"] = conversation_context
    if skill_name not in _SECURITY_SKILLS:
        return _augment_args(args, live_context)

    evidence = live_context or (
        "No live security evidence was returned. Treat scanner findings, reachability, "
        "and controls as unknown; do not ask the user to paste data as the workflow "
        "already attempted its read-only evidence collection."
    )
    if skill_name == "vuln_triage":
        args.update(
            {
                "findings": evidence,
                "context": (
                    "Use the provider posture, repository inventory, dependency "
                    "manifests, scanner artifacts, workflow files, and deployment "
                    "metadata already supplied in Findings as reachability context. "
                    "Do not request a second pasted copy of the evidence."
                ),
            }
        )
    else:
        args.update(
            {
                "controls": evidence,
                "framework": _security_framework(objective or task),
            }
        )
    return args


ORCHESTRATOR_SYSTEM_PROMPT = (
    "You are the DevSecOps Skills Suite assistant for a managed service, "
    "helping engineers and service leads across the delivery lifecycle: "
    "mobilise, baseline, transform, operate and improve. You are project-aware: "
    "use the PROJECT TOPOLOGY and live data already provided. Never pretend you "
    "lack access to repos, IaC, or cloud inventory that is present in context. "
    "Answer general questions directly and concisely. Prefer specialist skills "
    "for audits, IaC/Terraform generation, deployments, debugging, compliance, "
    "and reports. Never fabricate scan data, CVEs, or metrics the user did not "
    "provide, and always keep security and least-privilege front of mind. "
    "Provider deployment and resource-change requests are handled as structured "
    "az/aws/gh CLI actions or Terraform workflows, not as plain-text shell "
    "scripts: preserve the user's target and conversation context, ask only for "
    "genuinely missing deployment inputs, and never invent an image, repository, "
    "region, file, or subscription. For every proposed write, include a clear "
    "rollback plan. For read-only metrics/logs/cost/inventory/drift/posture: "
    "when Azure and/or GitHub are connected, DO NOT ask which subscription, "
    "resource group, or repository — use PROJECT TOPOLOGY and LIVE data for "
    "the connected subscription and mapped/named repos. When the user names a "
    "resource type or says all/every/existing, use every matching resource. "
    "Short follow-ups like 'container app', 'all', or 'every resource in the "
    "code' continue the prior diagnostic. In agent mode, report the work "
    "performed and its results; do not add an approval checkpoint or defer "
    "the response into a second plan."
)


def _orchestrator_system(policy: str, live_context: Optional[str] = None) -> str:
    from app.prompts import get_text_prompt

    base = get_text_prompt(
        "orchestrator-system",
        fallback=ORCHESTRATOR_SYSTEM_PROMPT,
    )
    system = f"{base}\n\n{policy}"
    if live_context:
        system += "\n\n" + live_context
    return system


def _gather_project_topology(
    project_id: str, messages: list[dict[str, Any]]
) -> str:
    """Build a complete project picture for planner and skill routing."""
    from app import chat_memory
    from app.project_context import gather_project_topology

    user_messages = [
        str(item.get("content", ""))
        for item in messages
        if item.get("role") == "user" and item.get("content")
    ][-8:]
    requirements: list[str] = []
    # Prefer structured requirements already stored for this chat when available.
    for item in messages:
        content = str(item.get("content", ""))
        if item.get("role") == "system" and "Requirements:" in content:
            for line in content.splitlines():
                if line.startswith("- "):
                    requirements.append(line[2:].strip())
    chat_id = None
    for item in messages:
        meta = item.get("meta") if isinstance(item.get("meta"), dict) else {}
        if meta.get("chat_id"):
            chat_id = str(meta["chat_id"])
            break
    if chat_id:
        try:
            requirements = chat_memory.get_requirements(chat_id) or requirements
        except Exception:  # noqa: BLE001
            pass
    return gather_project_topology(
        project_id,
        user_messages=user_messages,
        requirements=requirements or None,
    )


def _merge_context(*blocks: Optional[str]) -> Optional[str]:
    parts = [block for block in blocks if block]
    return "\n\n---\n\n".join(parts) if parts else None


def _clarification_reply(questions: list[str], summary: str = "") -> str:
    lines = [
        "I understand the request direction, but I need a few details before I continue:",
    ]
    for index, question in enumerate(questions[:5], start=1):
        lines.append(f"{index}. {question}")
    if summary:
        lines.extend(["", f"_Context:_ {summary}"])
    return "\n".join(lines)


@dataclass
class PlanStep:
    """One unit of work assigned to a single skill agent."""

    skill: str
    objective: str


@dataclass
class AgentRun:
    """The output of one skill agent within a task."""

    skill: str
    objective: str
    output: str


@dataclass
class ChatTurn:
    """The result of one orchestrated chat turn."""

    mode: Mode
    reply: str
    plan: list[PlanStep] = field(default_factory=list)
    agents: list[AgentRun] = field(default_factory=list)
    skills_used: list[str] = field(default_factory=list)
    charts: list[dict[str, Any]] = field(default_factory=list)
    needs_clarification: bool = False
    clarification_questions: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        payload = {
            "mode": self.mode,
            "reply": self.reply,
            "agents": [asdict(a) for a in self.agents],
            "skills_used": self.skills_used,
            "charts": self.charts,
            "needs_clarification": self.needs_clarification,
            "clarification_questions": self.clarification_questions,
        }
        if self.plan:
            payload["plan"] = [asdict(s) for s in self.plan]
        return payload


def _last_user_message(messages: list[dict[str, Any]]) -> str:
    for message in reversed(messages):
        if message.get("role") == "user":
            return message.get("content", "")
    return ""


def _memory_context_text(messages: list[dict[str, Any]]) -> str:
    """Extract bounded same-chat context already prepared by the API."""
    return "\n\n".join(
        str(message.get("content", ""))
        for message in messages
        if message.get("role") == "system"
        and (
            "CHAT MEMORY" in str(message.get("content", ""))
            or "RECENT CHAT TURNS" in str(message.get("content", ""))
        )
    )[:10000]


def _contextual_task(messages: list[dict[str, Any]]) -> str:
    """Combine the current request with bounded context for data routing.

    Skills still receive the current user request as their objective. This
    richer form is used for resolving references and fetching live data, where
    a follow-up like "show that for one hour" needs prior details.
    """
    task = _last_user_message(messages)
    context = _memory_context_text(messages)
    if not context:
        return task
    # Put the current request first so parsers prefer its new time window or
    # metric qualifier; the context supplies omitted resource names and scope.
    return f"CURRENT USER REQUEST:\n{task}\n\nCONVERSATION CONTEXT:\n{context}"[:18000]


def _skill_catalog_text() -> str:
    lines = []
    for skill in registry.all():
        if not getattr(skill, "auto_routable", True):
            continue
        triggers = "; ".join(skill.triggers[:3]) if skill.triggers else ""
        line = f"- {skill.name} ({skill.category}): {skill.description}"
        if triggers:
            line += f" [e.g. {triggers}]"
        lines.append(line)
    return "\n".join(lines)


PLANNER_SYSTEM_PROMPT_TEMPLATE = (
    "You are the routing planner for a DevSecOps Skills Suite. Your job is to "
    "decide — precisely — which specialist skills (if any) a user's request "
    "needs, and in what order.\n\n"
    "DECISION PROCEDURE:\n"
    "1. Determine the user's true intent using the current request PLUS "
    "accumulated requirements and PROJECT TOPOLOGY. Prefer evidence already in "
    "context over asking the user to paste files.\n"
    "2. Match intent to skills by capability, not keywords. Choose the MINIMAL "
    "set that fully satisfies the request — usually one skill. Add more only "
    "when the task genuinely has distinct sub-goals (e.g. 'audit my pipeline "
    "AND generate a hardened replacement' = two skills).\n"
    "3. Order steps by dependency: analysis/discovery before generation; "
    "Terraform generation before execution; debug after a failed deploy.\n"
    "4. Clarification is RARE. Set needs_clarification=true ONLY when a "
    "state-changing write cannot proceed without a missing concrete value "
    "(e.g. destroy vs create, missing region for a new resource). Do NOT ask "
    "which Container App / resource name for read-only metrics, logs, cost, "
    "inventory, drift, or posture when the user named a resource TYPE or said "
    "all/every/existing — route to the matching skill and let live discovery "
    "list every matching resource. NEVER ask which GitHub repo or Azure "
    "scope (subscription vs RG vs names) when PROJECT TOPOLOGY shows those "
    "providers connected — default to the connected subscription and mapped "
    "or named repos. Never clarify between CPU/memory vs requests when the "
    "user already said CPU/memory (or request metrics); include all of them.\n"
    "5. If NO skill fits — greeting or general question — return an EMPTY "
    "steps list so the assistant answers directly.\n\n"
    "Each step is executed by exactly one skill acting as an independent agent, "
    "so its objective must be self-contained and reference the relevant input. "
    "Never invent skills that are not in the catalog; use exact skill names.\n\n"
    "Respond ONLY with JSON of the form:\n"
    '{"reasoning": "<one or two sentences on why these skills>", '
    '"summary": "<one sentence plan overview>", '
    '"needs_clarification": false, '
    '"clarification_questions": [], '
    '"steps": ['
    '{"skill": "<exact skill name>", "objective": "<clear, self-contained '
    'instruction for that agent>"}]}\n\n'
    "Available skills:\n{{catalog}}"
)
# Back-compat alias used by older imports / docs.
PLANNER_SYSTEM_PROMPT = PLANNER_SYSTEM_PROMPT_TEMPLATE


def _build_plan(
    messages: list[dict[str, Any]], live_context: Optional[str] = None
) -> tuple[str, list[PlanStep], list[str]]:
    """Ask the planner LLM for an ordered set of skill steps.

    Returns ``(summary, steps, clarification_questions)``. When clarification
    questions are non-empty, the caller should ask the user instead of running.
    """
    catalog = _skill_catalog_text()
    from app.prompts import get_text_prompt

    system_content = get_text_prompt(
        "planner-system",
        fallback=PLANNER_SYSTEM_PROMPT_TEMPLATE,
        variables={"catalog": catalog},
    )
    if live_context:
        system_content += (
            "\n\nIMPORTANT: The user's live data and PROJECT TOPOLOGY have already "
            "been fetched (read-only) and will be handed to whichever skill you "
            "choose — this may include real source files, Terraform, and/or a live "
            "cloud/account inventory. Route by intent:\n"
            "- Design / generate Terraform for create/update/delete infra → "
            "'terraform_generator' (then 'terraform_executor' when applying).\n"
            "- End-to-end deploy / canary / rollout → 'deployment_manager'.\n"
            "- Debug a failed deploy / apply / build → 'infra_debugger'.\n"
            "- Deep analysis of an existing repo/app/infra layout → "
            "'project_analyzer'.\n"
            "- Multi-resource infra design without immediate TF → "
            "'infrastructure_architect'.\n"
            "- Reviewing Terraform / Bicep / IaC / Kubernetes / Dockerfiles → "
            "'iac_reviewer'.\n"
            "- Reviewing CI/CD pipelines, GitHub Actions or Azure DevOps YAML "
            "pipelines → 'pipeline_auditor'.\n"
            "- Reviewing / optimizing / refactoring APPLICATION source → "
            "'code_reviewer'.\n"
            "- Comparing LIVE infra against IaC/pipelines / drift / missing in "
            "code / every resource in the code → 'drift_auditor'.\n"
            "- Failed/unhealthy revision, crash, outage, logs → "
            "'incident_analyzer'.\n"
            "- Overall live cloud/account/repository security posture / public "
            "exposure → 'cloud_posture' (pair with 'drift_auditor' when the "
            "user also asks about IaC gaps).\n"
            "- Billing / cost / spend → 'cost_analyzer'.\n"
            "- Performance / metrics / CPU / memory / tokens / 'last 24 hours' / "
            "follow-ups like 'container app' or 'all' → 'metrics_analyzer'. Do "
            "NOT clarify the app name; live metrics below already enumerate "
            "resources when the user asked for all or a type.\n"
            "- Error / HTTP status counts / 4xx / 5xx → 'log_analyzer'.\n"
            "Never ask the user to paste files that are already provided below. "
            "Never ask which Azure app, subscription, resource group, or GitHub "
            "repo when PROVIDERS ARE CONNECTED or LIVE/TOPOLOGY data is present "
            "— use the connected subscription and mapped/named repositories."
        )
        system_content += "\n\n" + live_context
    planning_messages = [
        {
            "role": "system",
            "content": system_content,
        },
    ]
    memory_context = _memory_context_text(messages)
    if memory_context:
        planning_messages.append({"role": "system", "content": memory_context})
    planning_messages.append({"role": "user", "content": _last_user_message(messages)})
    completion = azure_client.chat(
        messages=planning_messages,
        temperature=0.1,
        response_format={"type": "json_object"},
    )
    raw = completion.choices[0].message.content or "{}"
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        parsed = {}

    summary = parsed.get("summary", "")
    questions = [
        str(item).strip()
        for item in (parsed.get("clarification_questions") or [])
        if str(item).strip()
    ][:5]
    # Live telemetry/inventory/topology already answers scope — do not block on it.
    live = live_context or ""
    task_text = _last_user_message(messages)
    contextual = _contextual_task(messages)
    discoverable = any(
        marker in live
        for marker in (
            "LIVE AZURE METRICS",
            "LIVE AZURE BILLING",
            "LIVE AZURE LOGS",
            "ENVIRONMENT DATA",
            "PROJECT TOPOLOGY",
            "LIVE GITHUB CODE",
            "DEFAULT AZURE SCOPE",
            "DEFAULT GITHUB SCOPE",
        )
    )
    questions = _filter_scope_clarifications(questions, live, contextual or task_text)
    if parsed.get("needs_clarification") and questions and not discoverable:
        # Still allow clarification for true write gaps, but drop questions that
        # only ask which existing Container App / resource to pick.
        useful = [
            q
            for q in questions
            if not re.search(
                r"which (azure )?(container )?app|which resource|app name|resource id",
                q,
                re.IGNORECASE,
            )
        ]
        useful = _filter_scope_clarifications(useful, live, contextual or task_text)
        if (
            useful
            and not _looks_like_metrics_followup(task_text)
            and not _looks_like_diagnostic_intent(contextual or task_text)
        ):
            return summary, [], useful[:5]
    steps: list[PlanStep] = []
    for item in parsed.get("steps", []):
        skill_name = item.get("skill", "")
        if registry.get(skill_name) is None:
            continue
        steps.append(
            PlanStep(skill=skill_name, objective=item.get("objective", ""))
        )
    # Metrics follow-ups must hit metrics_analyzer when the CURRENT turn is a
    # metrics ask/follow-up — never because an earlier turn left metrics in context.
    if not steps and (
        _looks_like_metrics_followup(task_text)
        or any(term in task_text.lower() for term in _METRIC_TRIGGERS)
    ):
        steps = [
            PlanStep(
                skill="metrics_analyzer",
                objective=(
                    "Answer the user's metrics/health question from the live Azure "
                    "Monitor data for every matching resource in scope. Do not ask "
                    "which app to target."
                ),
            )
        ]
    steps = _correct_misrouted_steps(task_text, steps, messages)
    # Drift / posture: connected Azure+GitHub means act, never interview.
    if (
        not steps
        and not _is_ack_or_policy_nudge(task_text)
        and (
        _looks_like_drift_intent(task_text)
        or _looks_like_drift_intent(contextual)
        or _looks_like_diagnostic_intent(contextual or task_text)
        )
    ):
        if _looks_like_drift_intent(task_text) or _looks_like_drift_intent(contextual):
            steps.append(
                PlanStep(
                    skill="drift_auditor",
                    objective=(
                        "Compare the live Azure subscription inventory against the "
                        "fetched GitHub IaC/pipelines (prefer any repo named by the "
                        "user). Report drift, resources in cloud-only / code-only, "
                        "and public-exposure gaps. Do not ask for Azure scope or "
                        "repository — both are already connected."
                    ),
                )
            )
        if _looks_like_posture_intent(task_text) or _looks_like_posture_intent(
            contextual
        ):
            if not any(step.skill == "cloud_posture" for step in steps):
                steps.append(
                    PlanStep(
                        skill="cloud_posture",
                        objective=(
                            "Review live Azure/GitHub posture for public exposure "
                            "and hardening gaps using connected inventory. Do not "
                            "ask which subscription or repo."
                        ),
                    )
                )
        if not steps:
            steps = [
                PlanStep(
                    skill="drift_auditor",
                    objective=(
                        "Run a read-only Azure vs GitHub drift/posture review from "
                        "connected providers. Do not ask for scope or repo."
                    ),
                )
            ]
    return summary, steps, []


DETAILED_PLAN_SYSTEM_PROMPT_TEMPLATE = (
    "You are a lead DevSecOps engineer scoping a piece of work and writing a "
    "DETAILED, researched plan BEFORE anything runs. You have already explored "
    "the user's environment: any live data and PROJECT TOPOLOGY below (their "
    "real repositories, cloud inventory, cost, source code, scan output, fresh "
    "vs existing mode) is the result of that exploration — read it carefully "
    "and ground every statement in it. Do NOT guess or hand-wave; if something "
    "is unknown, say precisely what you would check and where.\n\n"
    "Think like an engineer picking up a ticket and produce:\n"
    "1. UNDERSTANDING — restate, in your own words, exactly what the user wants "
    "and why, including whether this is a fresh or existing project.\n"
    "2. FINDINGS — what your exploration actually shows. Cite concrete specifics "
    "from the live data (repo names, resource counts, Terraform files, "
    "misconfigurations, cost drivers, file paths).\n"
    "3. ISSUES — the specific problems, risks or gaps this work must address, "
    "each tied to evidence from the findings.\n"
    "4. RESOLUTION — the approach you will take, preferring Terraform for "
    "infrastructure create/update/delete and including a rollback strategy.\n"
    "5. STEPS — an ordered TODO list where each item is executed by exactly ONE "
    "specialist skill (use exact catalog names). Order by dependency: "
    "explore/analyse before generate/apply; a later step may build on an "
    "earlier one. Each step has a self-contained 'objective' and a short "
    "'detail'.\n"
    "6. Clarification is RARE and only for missing write inputs. When Azure/"
    "GitHub are connected (see PROJECT TOPOLOGY / DEFAULT SCOPE notes), never "
    "ask which subscription, resource group, or repository — use connected "
    "defaults and named/mapped repos.\n\n"
    "If the request genuinely needs no specialist skill (a general question or "
    "greeting), return an empty steps list.\n\n"
    "Respond ONLY with JSON of the form:\n"
    '{"understanding": "<what the user wants>", '
    '"findings": "<what exploration shows, with specifics>", '
    '"issues": ["<issue tied to evidence>", ...], '
    '"resolution": "<the approach>", '
    '"needs_clarification": false, '
    '"clarification_questions": [], '
    '"steps": [{"skill": "<exact skill name>", "objective": "<instruction for '
    'that agent>", "detail": "<what this step does and why>"}]}\n\n'
    "Available skills:\n{{catalog}}"
)
DETAILED_PLAN_SYSTEM_PROMPT = DETAILED_PLAN_SYSTEM_PROMPT_TEMPLATE


def _build_detailed_plan(
    messages: list[dict[str, Any]], live_context: Optional[str] = None
) -> tuple[dict[str, Any], list[PlanStep]]:
    """Ask the planner LLM for a researched, detailed plan grounded in live data.

    Returns the parsed plan dict (understanding / findings / issues / resolution
    / steps) plus the validated, ordered PlanSteps used for execution.
    """
    catalog = _skill_catalog_text()
    from app.prompts import get_text_prompt

    system_content = get_text_prompt(
        "detailed-plan-system",
        fallback=DETAILED_PLAN_SYSTEM_PROMPT_TEMPLATE,
        variables={"catalog": catalog},
    )
    if live_context:
        system_content += (
            "\n\nLIVE EXPLORATION DATA (already fetched read-only from the user's "
            "connected accounts — base your understanding, findings and issues on "
            "this):\n" + live_context
        )
    planning_messages = [
        {"role": "system", "content": system_content},
    ]
    memory_context = _memory_context_text(messages)
    if memory_context:
        planning_messages.append({"role": "system", "content": memory_context})
    planning_messages.append({"role": "user", "content": _last_user_message(messages)})
    completion = azure_client.chat(
        messages=planning_messages,
        temperature=0.2,
        response_format={"type": "json_object"},
    )
    raw = completion.choices[0].message.content or "{}"
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        parsed = {}

    questions = [
        str(item).strip()
        for item in (parsed.get("clarification_questions") or [])
        if str(item).strip()
    ][:5]
    task_text = _last_user_message(messages)
    contextual = _contextual_task(messages)
    questions = _filter_scope_clarifications(
        questions, live_context, contextual or task_text
    )
    if (
        parsed.get("needs_clarification")
        and questions
        and not _looks_like_diagnostic_intent(contextual or task_text)
    ):
        parsed["clarification_questions"] = questions
        parsed["needs_clarification"] = True
        parsed["steps"] = []
        return parsed, []
    parsed["needs_clarification"] = False
    parsed["clarification_questions"] = []

    steps: list[PlanStep] = []
    valid_items: list[dict[str, Any]] = []
    for item in parsed.get("steps", []):
        skill_name = item.get("skill", "")
        if registry.get(skill_name) is None:
            continue
        steps.append(PlanStep(skill=skill_name, objective=item.get("objective", "")))
        valid_items.append(item)
    parsed["steps"] = valid_items
    return parsed, steps


def _run_single_skill(
    skill_name: str,
    task: str,
    policy: str,
    live_context: Optional[str],
    conversation_context: Optional[str] = None,
) -> ChatTurn:
    """Run one forced skill directly against the user's message."""
    skill = registry.get(skill_name)
    if skill is None:
        return ChatTurn(
            mode="agent",
            reply=f"Skill '{skill_name}' was not found.",
        )
    args = _skill_args(
        skill_name, task, task, policy, live_context, conversation_context
    )
    result = skill.run(args)
    return ChatTurn(
        mode="agent",
        reply=result.content,
        agents=[AgentRun(skill=skill_name, objective=task, output=result.content)],
        skills_used=[skill_name],
    )


def _synthesise(task: str, runs: list[AgentRun]) -> str:
    """Combine multiple agent outputs into a single coherent reply."""
    if len(runs) == 1:
        return runs[0].output

    joined = "\n\n".join(
        f"### Agent: {run.skill}\nObjective: {run.objective}\n\n{run.output}"
        for run in runs
    )
    messages = [
        {
            "role": "system",
            "content": (
                "You are the lead orchestrator. Several specialist agents have "
                "completed parts of a task. Synthesise their outputs into one "
                "clear, non-repetitive response for the user. Preserve concrete "
                "details (code, tables, findings). Open with a one-line summary "
                "of what was done, then present each agent's contribution under "
                "a clear heading. This is agent execution: do not add an approval "
                "checkpoint or defer the result into another plan."
            ),
        },
        {
            "role": "user",
            "content": f"Original task:\n{task}\n\nAgent outputs:\n{joined}",
        },
    ]
    completion = azure_client.chat(messages=messages, temperature=0.2)
    return completion.choices[0].message.content or joined


def _run_multi_agent(
    messages: list[dict[str, Any]],
    policy: str,
    live_context: Optional[str],
    project_id: str,
    charts: Optional[list[dict[str, Any]]] = None,
) -> ChatTurn:
    """Plan the task, run each step as a skill agent, then synthesise."""
    task = _last_user_message(messages)
    charts = charts or []
    summary, steps, questions = _build_plan(messages, live_context)
    if questions:
        return ChatTurn(
            mode="agent",
            reply=_clarification_reply(questions, summary),
            charts=charts,
            needs_clarification=True,
            clarification_questions=questions,
        )
    live_context, charts = _ensure_planned_context(
        task, project_id, steps, live_context, charts
    )

    if not steps:
        system = _orchestrator_system(policy, live_context)
        completion = azure_client.chat(
            messages=[
                {"role": "system", "content": system},
                *messages,
            ],
            temperature=0.3,
            name="orchestrator-direct",
        )
        return ChatTurn(
            mode="agent",
            reply=completion.choices[0].message.content or "",
            charts=charts,
        )

    runs: list[AgentRun] = []
    for step in steps:
        skill = registry.get(step.skill)
        if skill is None:
            continue
        args = _skill_args(
            step.skill,
            task,
            step.objective,
            policy,
            live_context,
            _memory_context_text(messages),
        )
        result = skill.run(args)
        runs.append(
            AgentRun(skill=step.skill, objective=step.objective, output=result.content)
        )

    reply = _synthesise(task, runs)
    return ChatTurn(
        mode="agent",
        reply=reply,
        agents=runs,
        skills_used=[run.skill for run in runs],
        charts=charts,
    )


def _format_detailed_plan(parsed: dict[str, Any], steps: list[PlanStep]) -> str:
    """Render the researched plan dict into a readable Markdown briefing."""
    lines: list[str] = []

    understanding = (parsed.get("understanding") or "").strip()
    if understanding:
        lines += ["## What you're asking for", understanding, ""]

    findings = (parsed.get("findings") or "").strip()
    if findings:
        lines += ["## What I found", findings, ""]

    issues = parsed.get("issues")
    if issues:
        lines.append("## Issues to address")
        if isinstance(issues, list):
            lines += [f"- {str(item).strip()}" for item in issues if str(item).strip()]
        else:
            lines.append(str(issues).strip())
        lines.append("")

    resolution = (parsed.get("resolution") or "").strip()
    if resolution:
        lines += ["## How I'll resolve it", resolution, ""]

    lines.append(f"## Plan — {len(steps)} step{'s' if len(steps) != 1 else ''}")
    valid_items = parsed.get("steps", [])
    for index, step in enumerate(steps, start=1):
        label = _pretty(step.skill)
        detail = ""
        if index - 1 < len(valid_items):
            detail = (valid_items[index - 1].get("detail") or "").strip()
        summary = detail or step.objective
        lines.append(f"{index}. **{label}** — {summary}")
    lines.append("")
    lines.append("_Review this plan, then approve below to run it._")
    return "\n".join(lines)


def _run_plan_mode(
    messages: list[dict[str, Any]], live_context: Optional[str]
) -> ChatTurn:
    """Explore, understand the request, and produce a detailed plan — no execution."""
    parsed, steps = _build_detailed_plan(messages, live_context)
    questions = [
        str(item).strip()
        for item in (parsed.get("clarification_questions") or [])
        if str(item).strip()
    ]
    task = _last_user_message(messages)
    contextual = _contextual_task(messages)
    questions = _filter_scope_clarifications(
        questions, live_context, contextual or task
    )
    if (
        questions
        and parsed.get("needs_clarification")
        and not _looks_like_diagnostic_intent(contextual or task)
    ):
        return ChatTurn(
            mode="plan",
            reply=_clarification_reply(questions, parsed.get("understanding") or ""),
            needs_clarification=True,
            clarification_questions=questions,
        )
    if not steps:
        understanding = (parsed.get("understanding") or "").strip()
        reply = understanding or (
            "This looks like a general question rather than a task needing a "
            "specialist skill. Ask it in agent mode and I'll answer directly."
        )
        return ChatTurn(mode="plan", reply=reply)

    return ChatTurn(
        mode="plan",
        reply=_format_detailed_plan(parsed, steps),
        plan=steps,
        skills_used=[step.skill for step in steps],
    )


def run_chat(
    messages: list[dict[str, Any]],
    project_id: str,
    mode: Mode = "agent",
    skill: Optional[str] = None,
    action_scope: ActionScope = "read_only",
    access_level: AccessLevel = "ask_approval",
    chat_id: str = "",
) -> ChatTurn:
    """Run one orchestrated turn.

    Args:
        messages: prior conversation (no system prompt; it is added here).
        project_id: the workspace whose credentials and repos are used.
        mode: "agent" to execute, "plan" to only plan.
        skill: optional forced skill name (from a /command).
        action_scope: "read_only" or "write" — gates change-producing behaviour.
        access_level: approval model for state-changing actions.
    """
    policy = build_agent_policy(action_scope, access_level) if mode == "agent" else build_policy(action_scope, access_level)
    task = _last_user_message(messages)
    contextual_task = _contextual_task(messages)
    topology = _gather_project_topology(project_id, messages)
    forced = registry.get(skill) if skill else None
    agentic = _is_agentic(forced)
    if agentic:
        live_context, charts = provider_status_text(project_id, action_scope), []
        live_context = _merge_context(topology, live_context)
    else:
        live_context, charts = _gather_live_context(
            contextual_task,
            project_id,
            force=(
                skill in {"cloud_posture", "drift_auditor"}
                or _looks_like_diagnostic_intent(contextual_task)
            ),
            force_cost=(skill == "cost_analyzer"),
            force_metrics=(skill == "metrics_analyzer"),
            force_logs=(skill == "log_analyzer"),
            force_security=(skill in _SECURITY_SKILLS or _is_security_task(task)),
        )
        status_context = provider_status_text(project_id, action_scope)
        live_context = _merge_context(topology, live_context, status_context)
    if mode == "plan" and agentic:
        args = _skill_args(skill, task, task, policy, live_context, _memory_context_text(messages))
        args.update({"project_id": project_id, "chat_id": chat_id, "plan_only": True})
        final: dict[str, Any] = {}
        for event in _stream_agentic(forced, args, chat_id=chat_id, plan_only=True):
            if event.get("type") == "final":
                final = event
        return ChatTurn(
            mode="plan",
            reply=str(final.get("reply") or ""),
            plan=[PlanStep(**step) for step in (final.get("plan") or []) if isinstance(step, dict) and step.get("skill")],
            skills_used=list(final.get("skills_used") or [skill]),
        )
    if mode == "plan":
        turn = _run_plan_mode(messages, live_context)
        turn.charts = charts
    elif skill:
        if agentic:
            args = _skill_args(skill, task, task, policy, live_context, _memory_context_text(messages))
            args.update({"project_id": project_id, "chat_id": chat_id})
            result = forced.run(args)
            turn = ChatTurn(
                mode="agent",
                reply=result.content,
                agents=[AgentRun(skill=skill, objective=task, output=result.content)],
                skills_used=[skill],
            )
        else:
            turn = _run_single_skill(
                skill, task, policy, live_context, _memory_context_text(messages)
            )
        turn.charts = charts
    else:
        turn = _run_multi_agent(messages, policy, live_context, project_id, charts)
    return turn


def _is_agentic(skill: Any) -> bool:
    return bool(skill is not None and getattr(skill, "is_agentic", False))


def _stream_agentic(
    skill: Any,
    args: dict[str, Any],
    *,
    chat_id: str,
    plan_only: bool = False,
) -> Iterator[dict[str, Any]]:
    payload = {**args, "plan_only": plan_only, "chat_id": chat_id, "thread_id": chat_id}
    collected: list[str] = []
    final: dict[str, Any] = {}
    for event in skill.stream_events(payload, chat_id=chat_id):
        if event.get("type") == "final":
            final = event
            continue
        if event.get("type") == "delta":
            collected.append(str(event.get("text") or ""))
        yield event
    reply = str(final.get("reply") or "".join(collected))
    mode = final.get("mode") or ("plan" if plan_only else "agent")
    turn = ChatTurn(
        mode=mode,
        reply=reply,
        plan=[
            PlanStep(skill=str(step.get("skill")), objective=str(step.get("objective")))
            for step in (final.get("plan") or [])
            if isinstance(step, dict) and step.get("skill")
        ],
        agents=[AgentRun(skill=skill.name, objective=str(args.get("objective") or ""), output=reply)],
        skills_used=list(final.get("skills_used") or [skill.name]),
    )
    result = turn.to_dict()
    if final.get("tier"):
        result["tier"] = final.get("tier")
        result["architect_mode"] = final.get("architect_mode")
    yield {"type": "final", **result}


def _pretty(name: str) -> str:
    return name.replace("_", " ").title()


def _skill_deltas(skill: Any, args: dict[str, Any]) -> Iterator[str]:
    """Yield text deltas for a skill run, streaming unless it emits JSON."""
    from app import observability

    # Bind only — do not wrap yields in tracing_context (StreamingResponse ContextVar issue).
    tokens = observability.bind_tracing(
        feature="skill",
        tags=["skill", skill.name],
        generation_name=f"skill-{skill.name}",
    )
    try:
        if getattr(skill, "is_agentic", False):
            for event in skill.stream_events(args, chat_id=str(args.get("chat_id") or "")):
                if event.get("type") == "delta" and event.get("text"):
                    yield str(event["text"])
            return
        if skill.json_output:
            yield skill.run(args).content
            return
        yield from azure_client.stream_chat(
            skill.build_messages(args),
            temperature=skill.temperature,
            name=f"skill-{skill.name}",
        )
    finally:
        observability.reset_tracing(tokens)


def _stream_and_collect(deltas: Iterator[str]) -> Iterator[dict[str, Any]]:
    """Forward deltas as events; the joined text is the generator's return."""
    acc: list[str] = []
    for piece in deltas:
        acc.append(piece)
        yield {"type": "delta", "text": piece}
    return "".join(acc)


def _stream_steps(
    task: str,
    messages: list[dict[str, Any]],
    steps: list[PlanStep],
    policy: str,
    live_context: Optional[str],
    charts: Optional[list[dict[str, Any]]] = None,
    chat_id: str = "",
    project_id: str = "",
) -> Iterator[dict[str, Any]]:
    """Execute an ordered set of skill steps, streaming events and a final turn.

    Shared by the auto agent path (after planning) and approved-plan execution.
    With no steps it answers directly; with one it streams that skill; with many
    it runs each skill then streams a synthesis. Any ``charts`` gathered from
    live data are attached to the final turn so the UI can plot them.
    """
    charts = charts or []
    if not steps:
        system = _orchestrator_system(policy, live_context)
        deltas = azure_client.stream_chat(
            [{"role": "system", "content": system}, *messages],
            temperature=0.3,
            name="orchestrator-direct",
        )
        content = yield from _stream_and_collect(deltas)
        turn = ChatTurn(mode="agent", reply=content, charts=charts)
        yield {"type": "final", **turn.to_dict()}
        return

    if len(steps) == 1:
        step = steps[0]
        sk = registry.get(step.skill)
        yield {"type": "status", "text": f"Running {_pretty(step.skill)}"}
        args = _skill_args(
            step.skill,
            task,
            step.objective,
            policy,
            live_context,
            _memory_context_text(messages),
        )
        args["chat_id"] = chat_id
        args["project_id"] = project_id
        if _is_agentic(sk):
            yield from _stream_agentic(sk, args, chat_id=chat_id)
            return
        content = yield from _stream_and_collect(_skill_deltas(sk, args))
        turn = ChatTurn(
            mode="agent",
            reply=content,
            agents=[AgentRun(skill=step.skill, objective=step.objective, output=content)],
            skills_used=[step.skill],
            charts=charts,
        )
        yield {"type": "final", **turn.to_dict()}
        return

    runs: list[AgentRun] = []
    for step in steps:
        sk = registry.get(step.skill)
        if sk is None:
            continue
        yield {"type": "status", "text": f"Running {_pretty(step.skill)}"}
        args = _skill_args(
            step.skill,
            task,
            step.objective,
            policy,
            live_context,
            _memory_context_text(messages),
        )
        args["chat_id"] = chat_id
        args["project_id"] = project_id
        if _is_agentic(sk):
            collected = []
            for event in sk.stream_events(args, chat_id=chat_id):
                if event.get("type") in {"status", "delta"}:
                    yield event
                if event.get("type") == "delta":
                    collected.append(str(event.get("text") or ""))
                if event.get("type") == "final":
                    collected = [str(event.get("reply") or "".join(collected))]
            result_content = "".join(collected)
            runs.append(AgentRun(skill=step.skill, objective=step.objective, output=result_content))
            continue
        result = sk.run(args)
        runs.append(
            AgentRun(skill=step.skill, objective=step.objective, output=result.content)
        )

    yield {"type": "status", "text": "Synthesizing"}
    joined = "\n\n".join(
        f"### Agent: {run.skill}\nObjective: {run.objective}\n\n{run.output}"
        for run in runs
    )
    synth_messages = [
        {
            "role": "system",
            "content": (
                "You are the lead orchestrator. Several specialist agents have "
                "completed parts of a task. Synthesise their outputs into one "
                "clear, non-repetitive response for the user. Preserve concrete "
                "details (code, tables, findings). Open with a one-line summary "
                "of what was done, then present each agent's contribution under "
                "a clear heading. This is agent execution: do not add an approval "
                "checkpoint or defer the result into another plan."
            ),
        },
        {"role": "user", "content": f"Original task:\n{task}\n\nAgent outputs:\n{joined}"},
    ]
    content = yield from _stream_and_collect(azure_client.stream_chat(synth_messages, 0.2))
    turn = ChatTurn(
        mode="agent",
        reply=content or joined,
        agents=runs,
        skills_used=[run.skill for run in runs],
        charts=charts,
    )
    yield {"type": "final", **turn.to_dict()}


def run_chat_stream(
    messages: list[dict[str, Any]],
    project_id: str,
    mode: Mode = "agent",
    skill: Optional[str] = None,
    action_scope: ActionScope = "read_only",
    access_level: AccessLevel = "ask_approval",
    chat_id: str = "",
) -> Iterator[dict[str, Any]]:
    """Streaming variant of run_chat.

    Yields event dicts: {"type": "status"|"delta"|"final", ...}. The final event
    carries the assembled reply plus mode / skills_used / plan / agents.
    """
    policy = build_agent_policy(action_scope, access_level) if mode == "agent" else build_policy(action_scope, access_level)
    task = _last_user_message(messages)
    contextual_task = _contextual_task(messages)
    topology = _gather_project_topology(project_id, messages)
    forced = registry.get(skill) if skill else None
    agentic = _is_agentic(forced)
    if agentic:
        live_context, charts = provider_status_text(project_id, action_scope), []
        live_context = _merge_context(topology, live_context)
    else:
        live_context, charts = _gather_live_context(
            contextual_task,
            project_id,
            force=(
                skill in {"cloud_posture", "drift_auditor"}
                or _looks_like_diagnostic_intent(contextual_task)
            ),
            force_cost=(skill == "cost_analyzer"),
            force_metrics=(skill == "metrics_analyzer"),
            force_logs=(skill == "log_analyzer"),
            force_security=(skill in _SECURITY_SKILLS or _is_security_task(task)),
        )
        status_context = provider_status_text(project_id, action_scope)
        live_context = _merge_context(topology, live_context, status_context)

    if mode == "plan" and agentic:
        args = _skill_args(skill, task, task, policy, live_context, _memory_context_text(messages))
        args.update({"project_id": project_id, "chat_id": chat_id})
        yield from _stream_agentic(forced, args, chat_id=chat_id, plan_only=True)
        return

    if mode == "plan":
        yield {"type": "status", "text": "Planning"}
        turn = _run_plan_mode(messages, live_context)
        for word in turn.reply.split(" "):
            yield {"type": "delta", "text": word + " "}
        yield {"type": "final", **turn.to_dict()}
        return

    if skill:
        sk = forced
        if sk is None:
            turn = ChatTurn(mode="agent", reply=f"Skill '{skill}' was not found.")
            yield {"type": "delta", "text": turn.reply}
            yield {"type": "final", **turn.to_dict()}
            return
        yield {"type": "status", "text": _pretty(skill)}
        args = _skill_args(
            skill, task, task, policy, live_context, _memory_context_text(messages)
        )
        args.update({"project_id": project_id, "chat_id": chat_id})
        if agentic:
            yield from _stream_agentic(sk, args, chat_id=chat_id)
            return
        content = yield from _stream_and_collect(_skill_deltas(sk, args))
        turn = ChatTurn(
            mode="agent",
            reply=content,
            agents=[AgentRun(skill=skill, objective=task, output=content)],
            skills_used=[skill],
            charts=charts,
        )
        yield {"type": "final", **turn.to_dict()}
        return

    yield {"type": "status", "text": "Analyzing request"}
    _summary, steps, questions = _build_plan(messages, live_context)
    if questions:
        turn = ChatTurn(
            mode="agent",
            reply=_clarification_reply(questions, _summary),
            charts=charts,
            needs_clarification=True,
            clarification_questions=questions,
        )
        for word in turn.reply.split(" "):
            yield {"type": "delta", "text": word + " "}
        yield {"type": "final", **turn.to_dict()}
        return
    live_context, charts = _ensure_planned_context(
        contextual_task, project_id, steps, live_context, charts
    )
    yield from _stream_steps(
        task, messages, steps, policy, live_context, charts, chat_id=chat_id, project_id=project_id
    )


def execute_plan_stream(
    messages: list[dict[str, Any]],
    project_id: str,
    steps: list[PlanStep],
    action_scope: ActionScope = "read_only",
    access_level: AccessLevel = "ask_approval",
    chat_id: str = "",
) -> Iterator[dict[str, Any]]:
    """Execute a plan the user already approved, streaming each step.

    The plan was produced earlier in plan mode; here we run it for real. Live
    context is (re)gathered so the skills operate on current data. Yields the
    same event shape as run_chat_stream.
    """
    policy = build_agent_policy(action_scope, access_level)
    task = _last_user_message(messages)
    contextual_task = _contextual_task(messages)
    valid = [step for step in steps if registry.get(step.skill) is not None]
    if not valid:
        turn = ChatTurn(
            mode="agent",
            reply="The approved plan had no runnable steps, so nothing was executed.",
        )
        yield {"type": "final", **turn.to_dict()}
        return
    topology = _gather_project_topology(project_id, messages)
    live_context, charts = _gather_live_context(contextual_task, project_id)
    live_context = _merge_context(topology, live_context)
    live_context, charts = _ensure_planned_context(
        contextual_task, project_id, valid, live_context, charts
    )
    yield {"type": "status", "text": "Executing plan"}
    yield from _stream_steps(
        task, messages, valid, policy, live_context, charts, chat_id=chat_id, project_id=project_id
    )
