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
from dataclasses import asdict, dataclass, field
from typing import Any, Iterator, Literal, Optional

from app import azure_client
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
        "irreversible or high-blast-radius actions explicitly."
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
    "ansible": ("ansible", "playbook"),
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
)
_DEFAULT_INFRA_KINDS = ("terraform", "bicep", "kubernetes", "dockerfile")

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


def _gather_code_context(task: str, project_id: str) -> Optional[str]:
    """Locate and fetch the real source files the user is asking about from GitHub."""
    if len(task) > _PASTED_CONTENT_CHARS or not github_infra.is_connected(project_id):
        return None
    kinds = _detect_code_kinds(task.lower())
    if not kinds:
        return None
    try:
        report = github_infra.build_code_report(project_id, kinds)
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


def _gather_cost_context(
    task: str, project_id: str, force: bool = False
) -> Optional[str]:
    """Fetch real Azure spend when the user asks about billing / cost."""
    task_lower = task.lower()
    if not force and not any(term in task_lower for term in _COST_TRIGGERS):
        return None
    if not azure_infra.is_connected(project_id):
        return None
    from_date, to_date, label = azure_infra.parse_cost_period(task)
    try:
        report = azure_infra.build_cost_report(project_id, from_date, to_date, label)
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


def _gather_live_context(
    task: str, project_id: str, force: bool = False, force_cost: bool = False
) -> Optional[str]:
    """Fetch live, read-only context from GitHub code and every relevant provider.

    Combines (a) real Azure spend when the user asks about billing/cost, (b) real
    source files located in the project's repos when they ask about Terraform /
    Bicep / Dockerfiles / K8s / pipelines / infra, and (c) live environment
    reports for each connected Azure / AWS / GitHub account relevant to the
    request. Everything is scoped to the given project. Returns the combined
    block, an error note to surface, or None when nothing relevant is connected.
    """
    task_lower = task.lower()
    blocks: list[str] = []
    cost_block = _gather_cost_context(task, project_id, force=force_cost)
    if cost_block:
        blocks.append(cost_block)
    code_block = _gather_code_context(task, project_id)
    if code_block:
        blocks.append(code_block)
    blocks.extend(
        block
        for spec in _PROVIDER_SPECS
        if (block := _provider_block(spec, force, task_lower, project_id))
    )
    return "\n\n---\n\n".join(blocks) if blocks else None


def _augment_args(args: dict[str, Any], live_context: Optional[str]) -> dict[str, Any]:
    if live_context:
        args = {**args, "live_environment": live_context}
    return args


ORCHESTRATOR_SYSTEM_PROMPT = (
    "You are the DevSecOps Skills Suite assistant for a managed service, "
    "helping engineers and service leads across the delivery lifecycle: "
    "mobilise, baseline, transform, operate and improve. Answer general "
    "questions directly and concisely. When a request would be better served "
    "by a specialist skill (auditing a pipeline, reviewing IaC, generating "
    "policy, triaging vulnerabilities, mapping compliance, analysing an "
    "incident, or writing a report), briefly say so and tell the user they can "
    "paste the relevant artefact or type '/' to invoke that skill. Never "
    "fabricate scan data, CVEs, or metrics the user did not provide, and always "
    "keep security and least-privilege front of mind."
)


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

    def to_dict(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "reply": self.reply,
            "plan": [asdict(s) for s in self.plan],
            "agents": [asdict(a) for a in self.agents],
            "skills_used": self.skills_used,
        }


def _last_user_message(messages: list[dict[str, Any]]) -> str:
    for message in reversed(messages):
        if message.get("role") == "user":
            return message.get("content", "")
    return ""


def _skill_catalog_text() -> str:
    lines = []
    for skill in registry.all():
        triggers = "; ".join(skill.triggers[:3]) if skill.triggers else ""
        line = f"- {skill.name} ({skill.category}): {skill.description}"
        if triggers:
            line += f" [e.g. {triggers}]"
        lines.append(line)
    return "\n".join(lines)


PLANNER_SYSTEM_PROMPT = (
    "You are the routing planner for a DevSecOps Skills Suite. Your job is to "
    "decide — precisely — which specialist skills (if any) a user's request "
    "needs, and in what order.\n\n"
    "DECISION PROCEDURE:\n"
    "1. Determine the user's true intent and the concrete artefacts they "
    "provided (a pipeline file, IaC, scan output, metrics, incident signals, "
    "a natural-language rule, etc.).\n"
    "2. Match intent to skills by capability, not keywords. Choose the MINIMAL "
    "set that fully satisfies the request — usually one skill. Add more only "
    "when the task genuinely has distinct sub-goals (e.g. 'audit my pipeline "
    "AND generate a hardened replacement' = two skills).\n"
    "3. Order steps by dependency: analysis/discovery before generation; a "
    "later step may build on an earlier step's output.\n"
    "4. If NO skill fits — the request is a general question, a greeting, or "
    "conversational — return an EMPTY steps list so the assistant answers "
    "directly. Do not force an irrelevant skill.\n\n"
    "Each step is executed by exactly one skill acting as an independent agent, "
    "so its objective must be self-contained and reference the relevant input. "
    "Never invent skills that are not in the catalog; use exact skill names.\n\n"
    "Respond ONLY with JSON of the form:\n"
    '{"reasoning": "<one or two sentences on why these skills>", '
    '"summary": "<one sentence plan overview>", "steps": ['
    '{"skill": "<exact skill name>", "objective": "<clear, self-contained '
    'instruction for that agent>"}]}\n\n'
    "Available skills:\n{catalog}"
)


def _build_plan(
    messages: list[dict[str, Any]], live_context: Optional[str] = None
) -> tuple[str, list[PlanStep]]:
    """Ask the planner LLM for an ordered set of skill steps."""
    catalog = _skill_catalog_text()
    system_content = PLANNER_SYSTEM_PROMPT.replace("{catalog}", catalog)
    if live_context:
        system_content += (
            "\n\nIMPORTANT: The user's live data has already been fetched "
            "(read-only) and will be handed to whichever skill you choose — this "
            "may include real source files located in their GitHub repositories "
            "and/or a live cloud/account inventory. Route by intent:\n"
            "- Reviewing Terraform / Bicep / IaC / Kubernetes / Dockerfiles → "
            "'iac_reviewer'.\n"
            "- Reviewing CI/CD pipelines or GitHub Actions workflows → "
            "'pipeline_auditor'.\n"
            "- Overall live cloud/account/repository security posture → "
            "'cloud_posture'.\n"
            "- Billing / cost / spend / invoice questions → 'cost_analyzer'.\n"
            "Never ask the user to paste files — the real code/inventory is "
            "already provided below and will reach the skill you pick."
        )
    planning_messages = [
        {
            "role": "system",
            "content": system_content,
        },
        {"role": "user", "content": _last_user_message(messages)},
    ]
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
    steps: list[PlanStep] = []
    for item in parsed.get("steps", []):
        skill_name = item.get("skill", "")
        if registry.get(skill_name) is None:
            continue
        steps.append(
            PlanStep(skill=skill_name, objective=item.get("objective", ""))
        )
    return summary, steps


DETAILED_PLAN_SYSTEM_PROMPT = (
    "You are a lead DevSecOps engineer scoping a piece of work and writing a "
    "DETAILED, researched plan BEFORE anything runs. You have already explored "
    "the user's environment: any live data below (their real repositories, cloud "
    "inventory, cost, source code, scan output) is the result of that "
    "exploration — read it carefully and ground every statement in it. Do NOT "
    "guess or hand-wave; if something is unknown, say precisely what you would "
    "check and where.\n\n"
    "Think like an engineer picking up a ticket and produce:\n"
    "1. UNDERSTANDING — restate, in your own words, exactly what the user wants "
    "and why.\n"
    "2. FINDINGS — what your exploration actually shows. Cite concrete specifics "
    "from the live data (repo names, resource counts, the actual "
    "misconfigurations, cost drivers, file paths). If no live data is present, "
    "state what inputs you still need to proceed.\n"
    "3. ISSUES — the specific problems, risks or gaps this work must address, "
    "each tied to evidence from the findings.\n"
    "4. RESOLUTION — the approach you will take to resolve those issues.\n"
    "5. STEPS — an ordered TODO list where each item is executed by exactly ONE "
    "specialist skill (use exact catalog names). Order by dependency: "
    "explore/analyse before generate/report; a later step may build on an "
    "earlier one. Each step has a self-contained 'objective' (the instruction "
    "the skill will receive) and a short 'detail' explaining what it does and "
    "why it matters here.\n\n"
    "If the request genuinely needs no specialist skill (a general question or "
    "greeting), return an empty steps list.\n\n"
    "Respond ONLY with JSON of the form:\n"
    '{"understanding": "<what the user wants>", '
    '"findings": "<what exploration shows, with specifics>", '
    '"issues": ["<issue tied to evidence>", ...], '
    '"resolution": "<the approach>", '
    '"steps": [{"skill": "<exact skill name>", "objective": "<instruction for '
    'that agent>", "detail": "<what this step does and why>"}]}\n\n'
    "Available skills:\n{catalog}"
)


def _build_detailed_plan(
    messages: list[dict[str, Any]], live_context: Optional[str] = None
) -> tuple[dict[str, Any], list[PlanStep]]:
    """Ask the planner LLM for a researched, detailed plan grounded in live data.

    Returns the parsed plan dict (understanding / findings / issues / resolution
    / steps) plus the validated, ordered PlanSteps used for execution.
    """
    catalog = _skill_catalog_text()
    system_content = DETAILED_PLAN_SYSTEM_PROMPT.replace("{catalog}", catalog)
    if live_context:
        system_content += (
            "\n\nLIVE EXPLORATION DATA (already fetched read-only from the user's "
            "connected accounts — base your understanding, findings and issues on "
            "this):\n" + live_context
        )
    planning_messages = [
        {"role": "system", "content": system_content},
        {"role": "user", "content": _last_user_message(messages)},
    ]
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
    skill_name: str, task: str, policy: str, live_context: Optional[str]
) -> ChatTurn:
    """Run one forced skill directly against the user's message."""
    skill = registry.get(skill_name)
    if skill is None:
        return ChatTurn(
            mode="agent",
            reply=f"Skill '{skill_name}' was not found.",
        )
    args = _augment_args({"input": task, "operating_policy": policy}, live_context)
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
                "a clear heading."
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
    messages: list[dict[str, Any]], policy: str, live_context: Optional[str]
) -> ChatTurn:
    """Plan the task, run each step as a skill agent, then synthesise."""
    task = _last_user_message(messages)
    summary, steps = _build_plan(messages, live_context)

    if not steps:
        system = f"{ORCHESTRATOR_SYSTEM_PROMPT}\n\n{policy}"
        if live_context:
            system += "\n\n" + live_context
        completion = azure_client.chat(
            messages=[
                {"role": "system", "content": system},
                *messages,
            ],
            temperature=0.3,
        )
        return ChatTurn(mode="agent", reply=completion.choices[0].message.content or "")

    runs: list[AgentRun] = []
    for step in steps:
        skill = registry.get(step.skill)
        if skill is None:
            continue
        args = _augment_args(
            {"task": task, "objective": step.objective, "operating_policy": policy},
            live_context,
        )
        result = skill.run(args)
        runs.append(
            AgentRun(skill=step.skill, objective=step.objective, output=result.content)
        )

    reply = _synthesise(task, runs)
    return ChatTurn(
        mode="agent",
        reply=reply,
        plan=steps,
        agents=runs,
        skills_used=[run.skill for run in runs],
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
    policy = build_policy(action_scope, access_level)
    task = _last_user_message(messages)
    live_context = _gather_live_context(
        task,
        project_id,
        force=(skill == "cloud_posture"),
        force_cost=(skill == "cost_analyzer"),
    )
    if mode == "plan":
        return _run_plan_mode(messages, live_context)
    if skill:
        return _run_single_skill(skill, task, policy, live_context)
    return _run_multi_agent(messages, policy, live_context)


def _pretty(name: str) -> str:
    return name.replace("_", " ").title()


def _skill_deltas(skill: Any, args: dict[str, Any]) -> Iterator[str]:
    """Yield text deltas for a skill run, streaming unless it emits JSON."""
    if skill.json_output:
        yield skill.run(args).content
        return
    yield from azure_client.stream_chat(
        skill.build_messages(args), temperature=skill.temperature
    )


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
) -> Iterator[dict[str, Any]]:
    """Execute an ordered set of skill steps, streaming events and a final turn.

    Shared by the auto agent path (after planning) and approved-plan execution.
    With no steps it answers directly; with one it streams that skill; with many
    it runs each skill then streams a synthesis.
    """
    if not steps:
        system = f"{ORCHESTRATOR_SYSTEM_PROMPT}\n\n{policy}"
        if live_context:
            system += "\n\n" + live_context
        deltas = azure_client.stream_chat(
            [{"role": "system", "content": system}, *messages], temperature=0.3
        )
        content = yield from _stream_and_collect(deltas)
        turn = ChatTurn(mode="agent", reply=content)
        yield {"type": "final", **turn.to_dict()}
        return

    if len(steps) == 1:
        step = steps[0]
        sk = registry.get(step.skill)
        yield {"type": "status", "text": f"Running {_pretty(step.skill)}"}
        args = _augment_args(
            {"task": task, "objective": step.objective, "operating_policy": policy},
            live_context,
        )
        content = yield from _stream_and_collect(_skill_deltas(sk, args))
        turn = ChatTurn(
            mode="agent",
            reply=content,
            plan=steps,
            agents=[AgentRun(skill=step.skill, objective=step.objective, output=content)],
            skills_used=[step.skill],
        )
        yield {"type": "final", **turn.to_dict()}
        return

    runs: list[AgentRun] = []
    for step in steps:
        sk = registry.get(step.skill)
        if sk is None:
            continue
        yield {"type": "status", "text": f"Running {_pretty(step.skill)}"}
        args = _augment_args(
            {"task": task, "objective": step.objective, "operating_policy": policy},
            live_context,
        )
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
                "a clear heading."
            ),
        },
        {"role": "user", "content": f"Original task:\n{task}\n\nAgent outputs:\n{joined}"},
    ]
    content = yield from _stream_and_collect(azure_client.stream_chat(synth_messages, 0.2))
    turn = ChatTurn(
        mode="agent",
        reply=content or joined,
        plan=steps,
        agents=runs,
        skills_used=[run.skill for run in runs],
    )
    yield {"type": "final", **turn.to_dict()}


def run_chat_stream(
    messages: list[dict[str, Any]],
    project_id: str,
    mode: Mode = "agent",
    skill: Optional[str] = None,
    action_scope: ActionScope = "read_only",
    access_level: AccessLevel = "ask_approval",
) -> Iterator[dict[str, Any]]:
    """Streaming variant of run_chat.

    Yields event dicts: {"type": "status"|"delta"|"final", ...}. The final event
    carries the assembled reply plus mode / skills_used / plan / agents.
    """
    policy = build_policy(action_scope, access_level)
    task = _last_user_message(messages)
    live_context = _gather_live_context(
        task,
        project_id,
        force=(skill == "cloud_posture"),
        force_cost=(skill == "cost_analyzer"),
    )

    if mode == "plan":
        yield {"type": "status", "text": "Planning"}
        turn = _run_plan_mode(messages, live_context)
        for word in turn.reply.split(" "):
            yield {"type": "delta", "text": word + " "}
        yield {"type": "final", **turn.to_dict()}
        return

    if skill:
        sk = registry.get(skill)
        if sk is None:
            turn = ChatTurn(mode="agent", reply=f"Skill '{skill}' was not found.")
            yield {"type": "delta", "text": turn.reply}
            yield {"type": "final", **turn.to_dict()}
            return
        yield {"type": "status", "text": _pretty(skill)}
        args = _augment_args({"input": task, "operating_policy": policy}, live_context)
        content = yield from _stream_and_collect(_skill_deltas(sk, args))
        turn = ChatTurn(
            mode="agent",
            reply=content,
            agents=[AgentRun(skill=skill, objective=task, output=content)],
            skills_used=[skill],
        )
        yield {"type": "final", **turn.to_dict()}
        return

    yield {"type": "status", "text": "Analyzing request"}
    _summary, steps = _build_plan(messages, live_context)
    yield from _stream_steps(task, messages, steps, policy, live_context)


def execute_plan_stream(
    messages: list[dict[str, Any]],
    project_id: str,
    steps: list[PlanStep],
    action_scope: ActionScope = "read_only",
    access_level: AccessLevel = "ask_approval",
) -> Iterator[dict[str, Any]]:
    """Execute a plan the user already approved, streaming each step.

    The plan was produced earlier in plan mode; here we run it for real. Live
    context is (re)gathered so the skills operate on current data. Yields the
    same event shape as run_chat_stream.
    """
    policy = build_policy(action_scope, access_level)
    task = _last_user_message(messages)
    valid = [step for step in steps if registry.get(step.skill) is not None]
    if not valid:
        turn = ChatTurn(
            mode="agent",
            reply="The approved plan had no runnable steps, so nothing was executed.",
        )
        yield {"type": "final", **turn.to_dict()}
        return
    live_context = _gather_live_context(task, project_id)
    yield {"type": "status", "text": "Executing plan"}
    yield from _stream_steps(task, messages, valid, policy, live_context)
