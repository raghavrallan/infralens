"""Skill: analyse live resource metrics (CPU, utilization) over a time window."""
from app.skills.base import Skill


class MetricsAnalyzerSkill(Skill):
    name = "metrics_analyzer"
    category = "Observability & performance"
    description = (
        "Answer performance / telemetry questions about the user's CONNECTED "
        "cloud resources using live metrics the suite pulls from Azure Monitor "
        "(e.g. Container App or VM CPU over the last 24 hours). Use this whenever "
        "the user asks for 'metrics', 'CPU', 'memory', 'utilization', 'usage', "
        "'the last 24 hours', or a graph of a resource — the real time series is "
        "provided, so never ask them to paste telemetry."
    )
    triggers = [
        "give me the last 24 hour cpu metrics of my container app",
        "what's the cpu utilization of my vm over the last day",
        "show me a graph of my container app cpu",
        "how busy has my app been this week",
    ]
    parameters = {
        "type": "object",
        "properties": {
            "objective": {
                "type": "string",
                "description": "The metric / performance question to answer.",
            }
        },
        "required": ["objective"],
    }
    wiki = (
        "## Metrics & Performance Analyst\n\n"
        "Answers performance questions from your *connected* cloud resources using "
        "live time series pulled read-only from Azure Monitor — no telemetry "
        "pasting required. The chat renders the series as a graph you can switch "
        "between line and bar.\n\n"
        "### When to use it\n"
        "- 'Give me the last 24 hours of CPU for my container app.'\n"
        "- 'What's the CPU utilization of my VM this week?'\n"
        "- 'Show me a graph of my app's CPU usage.'\n\n"
        "### What it uses\n"
        "The Azure connection saved in Settings for the active project. It "
        "discovers the resource (Container Apps by default, or VMs when asked), "
        "reads its CPU time series over the requested window, and reasons over "
        "the real samples. A subscription id must be set and the app registration "
        "needs at least the *Monitoring Reader* (or Reader) role.\n\n"
        "### What you get back\n"
        "A concise read of average, peak and minimum CPU, notable spikes, and a "
        "plotted graph. It never changes anything.\n\n"
        "### Maps to\n"
        "Operating model control point: *Observability & performance*."
    )
    system_prompt = (
        "You are a senior SRE answering performance/telemetry questions about a "
        "customer's LIVE Azure resources. You are given the REAL metric summary "
        "for the requested window — one block per metric, with per-resource "
        "average, peak and minimum — fetched read-only from Azure Monitor, and "
        "each metric is plotted for the user as its own graph. Reason ONLY over "
        "the figures provided; never invent samples, metrics, resources or time "
        "ranges.\n\n"
        "CRITICAL: Cover EVERY metric present in the data. If the user asked for "
        "several metrics (e.g. CPU and memory) address each one; if the data "
        "notes a requested metric had no data or was unavailable for this "
        "resource type, say so plainly instead of silently dropping it. Use the "
        "exact unit shown for each metric (%, MB, ms, count, /s, …) and the "
        "window given — do not relabel or assume a different window.\n\n"
        "NEVER ask which Azure app/resource to target when live metrics are "
        "present, when the user named a resource type (Container App), or when "
        "they said all/every/existing. Report every resource in the data. If no "
        "live metrics block is present, say discovery failed and what role is "
        "needed — do not interview the user for an app name they already scoped.\n\n"
        "METHOD:\n"
        "- Answer the user's actual question first and directly.\n"
        "- For each metric, call out the average, peak and minimum, and any "
        "notable spikes or flat periods; if several resources are present, "
        "compare them.\n"
        "- Interpret what the pattern implies (head-room, right-sizing, possible "
        "throttling, saturation or scale events) — but only what the data "
        "supports.\n\n"
        "OUTPUT (Markdown):\n"
        "- A one-line headline with the key numbers and the window.\n"
        "- For each metric, a short summary table: Resource | Avg | Peak | Min.\n"
        "- A brief 'What this means' note with pragmatic, read-only suggestions.\n"
        "- Mention that the graph(s) above/alongside plot the same series.\n\n"
        "GUARDRAILS — READ-ONLY. Interpret and advise; never present changes as "
        "applied and never output commands unless explicitly asked."
    )


skill = MetricsAnalyzerSkill()
