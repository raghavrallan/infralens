"""Skill: answer error / HTTP status questions from live request telemetry."""
from app.skills.base import Skill


class LogAnalyzerSkill(Skill):
    name = "log_analyzer"
    category = "Observability & performance"
    description = (
        "Answer questions about errors and HTTP status codes in the user's "
        "CONNECTED container apps using live request telemetry the suite pulls "
        "from Azure Monitor (e.g. 'how many 400 errors', 'any 500s in the last "
        "hour', 'error rate today'). Real per-status counts are provided, so "
        "never ask the user to paste logs."
    )
    triggers = [
        "how many 400 errors are in my container app logs",
        "any 500 errors in the last hour",
        "show me the 4xx and 5xx counts for the last 2 hours",
        "what's the error rate on my container app today",
    ]
    parameters = {
        "type": "object",
        "properties": {
            "objective": {
                "type": "string",
                "description": "The error / status-code question to answer.",
            }
        },
        "required": ["objective"],
    }
    wiki = (
        "## Log & Error Analyst\n\n"
        "Answers error and HTTP status questions for your *connected* container "
        "apps using live request telemetry pulled read-only from Azure Monitor — "
        "no log pasting required. The chat renders 4xx / 5xx counts over time as a "
        "graph.\n\n"
        "### When to use it\n"
        "- 'How many 400 errors do we have in the last hour?'\n"
        "- 'Any 500s in the last 2 hours?'\n"
        "- 'What's the 4xx / 5xx breakdown today?'\n\n"
        "### What it uses\n"
        "The Azure connection saved in Settings for the active project. It reads "
        "the Container Apps `Requests` metric split by HTTP status code over the "
        "requested window. A subscription id must be set and the app registration "
        "needs at least the *Monitoring Reader* (or Reader) role.\n\n"
        "### What you get back\n"
        "Total requests, a by-category (2xx/3xx/4xx/5xx) and by-code breakdown, the "
        "specific codes you asked about, and a plotted error graph. It never "
        "changes anything.\n\n"
        "### Maps to\n"
        "Operating model control point: *Observability & performance*."
    )
    system_prompt = (
        "You are a senior SRE answering error / HTTP status questions about a "
        "customer's LIVE Azure container apps. You are given REAL request counts "
        "by HTTP status code for the requested window — fetched read-only from "
        "Azure Monitor's Requests metric — and 4xx/5xx are plotted for the user. "
        "Reason ONLY over the figures provided; never invent counts, codes, "
        "resources or time ranges.\n\n"
        "METHOD:\n"
        "- Answer the user's actual question first and directly (e.g. the exact "
        "number of 400s or 500s in the window they named), using the window "
        "shown.\n"
        "- Then give the by-category breakdown (2xx/3xx/4xx/5xx) and call out any "
        "notable error codes.\n"
        "- Interpret briefly: is the error rate meaningful relative to total "
        "traffic, is it concentrated on one app, is it a spike or steady — but "
        "only what the data supports. If a requested code had zero occurrences, "
        "say so plainly.\n\n"
        "OUTPUT (Markdown):\n"
        "- A one-line headline with the key error counts and the window.\n"
        "- A short table: Resource | 2xx | 3xx | 4xx | 5xx | Total (only for the "
        "categories present).\n"
        "- A brief 'What this means' note.\n"
        "- Mention the graph plots 4xx / 5xx over time.\n\n"
        "GUARDRAILS — READ-ONLY. Interpret and advise; never present changes as "
        "applied and never output commands unless explicitly asked."
    )


skill = LogAnalyzerSkill()
