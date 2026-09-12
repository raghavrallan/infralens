"""Skill: triage and prioritise vulnerability scan results."""
from __future__ import annotations

import json
from typing import Any

from app.skills.base import Skill, SkillResult


def format_vuln_triage_markdown(raw: str) -> str:
    """Turn the skill's JSON payload into Markdown for chat rendering.

    Structured JSON is still produced by the model (json_output=True) so
    downstream extractors can use metadata["raw_json"]. Chat must never show
    the raw object blob.
    """
    text = (raw or "").strip()
    if not text:
        return text
    try:
        data = json.loads(text)
    except (ValueError, json.JSONDecodeError):
        return raw
    if not isinstance(data, dict):
        return raw

    summary = str(data.get("summary") or "").strip()
    highest = str(data.get("highest_priority") or "").strip()
    findings = data.get("findings")
    if not isinstance(findings, list):
        findings = []

    lines: list[str] = []
    if summary:
        lines.append(summary)
        lines.append("")
    if highest:
        lines.append(f"**Highest priority:** {highest}")
        lines.append("")

    if not findings:
        lines.append("No discrete vulnerability findings were produced from the evidence.")
        return "\n".join(lines).strip()

    lines.append("### Findings")
    lines.append("")
    for idx, item in enumerate(findings, start=1):
        if not isinstance(item, dict):
            continue
        title = str(
            item.get("title")
            or item.get("cve_id")
            or item.get("cveid")
            or f"Finding {idx}"
        ).strip()
        cve = str(item.get("cve_id") or item.get("cveid") or "").strip()
        component = str(item.get("affected_component") or "").strip()
        priority = str(item.get("priority") or "").strip()
        fix = str(item.get("fix_action") or "").strip()
        reasoning = str(item.get("reasoning") or "").strip()
        sources = item.get("sources") if isinstance(item.get("sources"), list) else []
        reachable = item.get("reachable")
        exploitable = item.get("exploitable")

        heading = f"{idx}. {title}"
        if cve and cve.upper() not in ("N/A", "NA", "NONE") and cve not in title:
            heading = f"{idx}. {cve} — {title}"
        lines.append(f"**{heading}**")
        if priority:
            lines.append(f"- **Severity / priority:** {priority}")
        if component:
            lines.append(f"- **Affected:** {component}")
        if reachable is not None:
            lines.append(f"- **Reachable:** {_bool_label(reachable)}")
        if exploitable is not None:
            lines.append(f"- **Exploitable:** {_bool_label(exploitable)}")
        if fix:
            lines.append(f"- **Fix:** {fix}")
        if reasoning:
            lines.append(f"- **Reasoning:** {reasoning}")
        if sources:
            src_text = "; ".join(str(s).strip() for s in sources if str(s).strip())
            if src_text:
                lines.append(f"- **Evidence:** {src_text}")
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def _bool_label(value: Any) -> str:
    if value is True:
        return "yes"
    if value is False:
        return "no"
    return "unknown"


class VulnTriageSkill(Skill):
    name = "vuln_triage"
    category = "Observability & response"
    description = (
        "Triage vulnerability findings from one or more scanners (Snyk, Trivy, "
        "Checkmarx, Prisma), deduplicate, assess reachability/exploitability, "
        "and produce a prioritised, actionable list."
    )
    triggers = [
        "triage these vulnerabilities",
        "prioritise my snyk findings",
        "help me deduplicate scan results",
    ]
    parameters = {
        "type": "object",
        "properties": {
            "findings": {
                "type": "string",
                "description": (
                    "Raw scanner output or a list of CVEs/findings, ideally "
                    "from multiple tools."
                ),
            },
            "context": {
                "type": "string",
                "description": (
                    "Optional codebase/runtime context: which components are "
                    "internet-facing, which dependencies are actually used."
                ),
            },
        },
        "required": ["findings"],
    }
    json_output = True
    system_prompt = (
        "You are a vulnerability triage specialist who cuts scanner noise down "
        "to the few findings that actually matter. You reason about real "
        "risk — reachability and exploitability in THIS system — not raw CVSS.\n\n"
        "METHOD:\n"
        "1. Normalise & deduplicate: the same CVE reported by multiple tools is "
        "ONE finding; record which tools flagged it.\n"
        "2. Reachability: is the vulnerable function/component actually invoked "
        "or exposed given the provided context? Unreachable code drops in "
        "priority.\n"
        "3. Exploitability: weigh known-exploited status (KEV-style), whether "
        "the component is internet-facing, auth requirements, and whether it is "
        "a direct or transitive dependency. Prefer exploit-likelihood signals "
        "(EPSS-style reasoning) over base severity alone.\n"
        "4. Prioritise into Critical / High / Medium / Low with an explicit "
        "'fix now / this sprint / backlog / accept' recommendation.\n"
        "5. Fix action: the exact fixed version to upgrade to, or a concrete "
        "mitigation/compensating control when no fix exists.\n\n"
        "EVIDENCE HANDLING:\n"
        "- The findings input is a read-only evidence bundle assembled from the "
        "user's connected repositories and cloud accounts. It may contain scanner "
        "reports, dependency manifests, lockfiles, SBOMs, workflow configuration, "
        "repository security settings, and deployment context. Use all of it.\n"
        "- If no CVE-level scanner results are present, do not ask the user to paste "
        "them and do not turn that absence into a vulnerability. Return findings=[] "
        "and explain what evidence was reviewed and what coverage remains unknown.\n"
        "- Treat provider fetch failures and missing files as coverage limitations, "
        "not as scanner findings. Never invent a CVE, package version, reachability "
        "signal, or exploit status.\n"
        "- Use exact repository/path and provider evidence as sources whenever it is "
        "available. Keep reachability and exploitability unknown when the bundle "
        "does not prove them.\n\n"
        "Respond ONLY with a JSON object of the form: {\"summary\": string, "
        "\"highest_priority\": string, \"findings\": [{\"cve_id\": string, "
        "\"title\": string, \"affected_component\": string, \"sources\": "
        "[string], \"reachable\": boolean, \"exploitable\": boolean, "
        "\"priority\": string, \"fix_action\": string, \"reasoning\": string}]}. "
        "Order findings from highest to lowest priority. Never fabricate CVEs, "
        "versions, or exploit status not supported by the input; if a signal is "
        "unknown, say so in the reasoning rather than guessing."
    )

    def run(self, args: dict[str, Any]) -> SkillResult:
        result = super().run(args)
        raw = result.content or ""
        result.metadata["raw_json"] = raw
        result.content = format_vuln_triage_markdown(raw)
        return result


skill = VulnTriageSkill()
