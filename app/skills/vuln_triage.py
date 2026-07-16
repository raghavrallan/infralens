"""Skill: triage and prioritise vulnerability scan results."""
from app.skills.base import Skill


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
    wiki = (
        "## Vuln Triage\n\n"
        "Takes noisy scanner output from multiple tools and turns it into a "
        "short, prioritised, de-duplicated action list.\n\n"
        "### When to use it\n"
        "- After running Snyk / Trivy / Checkmarx / Prisma and facing hundreds "
        "of findings.\n"
        "- Daily vulnerability triage during the *Operate* phase.\n\n"
        "### What to give it\n"
        "- The raw findings (ideally from more than one tool) and optional "
        "context about which components are internet-facing or actually used.\n\n"
        "### What you get back\n"
        "Structured JSON: a summary plus per-finding CVE id, affected "
        "component, reachability, exploitability, priority, fix action and "
        "reasoning. It will not fabricate CVEs that are not in your input.\n\n"
        "### Maps to\n"
        "Operating model control point: *Observability & response*."
    )
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
        "Respond ONLY with a JSON object of the form: {\"summary\": string, "
        "\"highest_priority\": string, \"findings\": [{\"cve_id\": string, "
        "\"title\": string, \"affected_component\": string, \"sources\": "
        "[string], \"reachable\": boolean, \"exploitable\": boolean, "
        "\"priority\": string, \"fix_action\": string, \"reasoning\": string}]}. "
        "Order findings from highest to lowest priority. Never fabricate CVEs, "
        "versions, or exploit status not supported by the input; if a signal is "
        "unknown, say so in the reasoning rather than guessing."
    )


skill = VulnTriageSkill()
