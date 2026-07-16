"""Skill: turn raw service metrics into an executive-ready report."""
from app.skills.base import Skill


class ReportWriterSkill(Skill):
    name = "report_writer"
    category = "Executive transparency"
    description = (
        "Turn raw service metrics (DORA, SLA, vulnerabilities, cost) into an "
        "executive-ready monthly/quarterly report with narrative and "
        "recommendations."
    )
    triggers = [
        "write a monthly service report",
        "summarise these dora metrics for execs",
        "create a quarterly review from this data",
    ]
    parameters = {
        "type": "object",
        "properties": {
            "metrics": {
                "type": "string",
                "description": "Raw metrics/KPIs, trends, and any notable events.",
            },
            "period": {
                "type": "string",
                "description": "Reporting period, e.g. 'March 2026' or 'Q1 2026'.",
            },
            "audience": {
                "type": "string",
                "description": "Intended audience, e.g. 'CTO', 'client execs'.",
            },
        },
        "required": ["metrics"],
    }
    wiki = (
        "## Report Writer\n\n"
        "Turns raw service metrics into a board-readable report with narrative "
        "and next-period priorities.\n\n"
        "### When to use it\n"
        "- Monthly service reviews and quarterly business reviews.\n"
        "- Any time you need to translate DORA/SLA/cost numbers into an "
        "executive story.\n\n"
        "### What to give it\n"
        "- The raw metrics/KPIs and notable events, the reporting period, and "
        "the intended audience.\n\n"
        "### What you get back\n"
        "A structured report: executive summary, release confidence, service "
        "resilience, risk & compliance, cost/FinOps highlights and next-period "
        "priorities. It leads with outcomes and flags missing metrics rather "
        "than inventing them.\n\n"
        "### Maps to\n"
        "Operating model control point: *Executive transparency*."
    )
    system_prompt = (
        "You are a service delivery lead writing the executive report for a "
        "managed DevSecOps service. You translate operational metrics into a "
        "business narrative an executive can act on in two minutes — outcomes "
        "and trends first, numbers in support.\n\n"
        "METHOD:\n"
        "1. Interpret the metrics: state the trend (improving/steady/declining) "
        "and what it means for the business, not just the value.\n"
        "2. Benchmark against agreed targets or DORA performance bands where a "
        "target is provided; do not assume targets that were not given.\n"
        "3. Be balanced and non-defensive: call out wins and regressions "
        "plainly, and tie each risk to an owner or next step.\n\n"
        "SECTIONS (Markdown):\n"
        "- Executive summary — 3-4 sentences leading with the headline.\n"
        "- Release confidence — lead time, deployment frequency, change-failure "
        "rate.\n"
        "- Service resilience — availability, MTTR, incident trend.\n"
        "- Risk & compliance — vulnerability remediation, policy compliance, "
        "audit evidence.\n"
        "- Cost / FinOps — spend trend and efficiency highlights.\n"
        "- Next-period priorities — a short ranked list.\n\n"
        "GUARDRAILS — use only the metrics provided; where a section's data is "
        "missing, say 'not reported this period' rather than inventing figures. "
        "Round sensibly and keep it board-readable."
    )


skill = ReportWriterSkill()
