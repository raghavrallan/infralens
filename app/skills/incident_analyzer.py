"""Skill: analyse incident signals and propose root cause + remediation."""
from app.skills.base import Skill


class IncidentAnalyzerSkill(Skill):
    name = "incident_analyzer"
    category = "Observability & response"
    description = (
        "Analyse incident signals (logs, metrics, traces, alerts, recent "
        "changes) to propose a likely root cause, remediation steps, and a "
        "draft post-mortem."
    )
    triggers = [
        "help me analyse this incident",
        "what's the root cause of these logs",
        "why is my service down",
    ]
    parameters = {
        "type": "object",
        "properties": {
            "signals": {
                "type": "string",
                "description": "Logs, metrics, traces, alerts or symptoms.",
            },
            "recent_changes": {
                "type": "string",
                "description": "Recent deployments/config changes, if known.",
            },
        },
        "required": ["signals"],
    }
    wiki = (
        "## Incident Analyzer\n\n"
        "Correlates incident signals into a likely root cause, remediation "
        "steps and a draft post-mortem — fast, during the pressure of an "
        "incident.\n\n"
        "### When to use it\n"
        "- Live incident response when you need a second pair of eyes on logs "
        "and metrics.\n"
        "- Writing the blameless post-mortem afterwards.\n\n"
        "### What to give it\n"
        "- The signals (logs, metrics, traces, alerts, symptoms) and any recent "
        "deployments or config changes.\n\n"
        "### What you get back\n"
        "Impact and blast-radius summary, the most probable root cause with "
        "confidence and evidence (plus alternates), immediate mitigation and a "
        "longer-term fix, and a short post-mortem draft. It is explicit about "
        "assumptions and what data would raise confidence.\n\n"
        "### Maps to\n"
        "Operating model control point: *Observability & response*."
    )
    system_prompt = (
        "You are a staff SRE leading incident analysis under pressure. You "
        "reason from evidence to hypotheses like a diagnostician, correlate "
        "signals with recent changes, and are honest about uncertainty.\n\n"
        "METHOD:\n"
        "1. Impact: state what is broken, since when, and the blast radius "
        "(users, services, data) inferred strictly from the signals.\n"
        "2. Timeline: reconstruct the sequence of events from timestamps in the "
        "logs/metrics and any recent deploys or config changes.\n"
        "3. Correlation: connect symptoms to a change or trigger; distinguish "
        "the proximate cause from contributing factors.\n"
        "4. Hypotheses: give the most probable root cause with a confidence "
        "level (high/medium/low) and the exact evidence supporting it; list "
        "plausible alternates and how to confirm or rule each out.\n"
        "5. Response: immediate mitigation (stop the bleeding — rollback, "
        "scale, failover, flag) and the durable fix.\n"
        "6. Post-mortem: a short blameless draft — summary, timeline, root "
        "cause, impact, and specific action items with owners/type.\n\n"
        "OUTPUT — clear Markdown with those sections.\n\n"
        "GUARDRAILS — never assert a root cause as certain when the evidence is "
        "circumstantial; label confidence and name the single piece of data "
        "that would most increase it. Do not invent log lines or metrics."
    )


skill = IncidentAnalyzerSkill()
