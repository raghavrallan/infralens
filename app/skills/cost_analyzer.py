"""Skill: analyse live cloud spend and answer billing questions (FinOps)."""
from app.skills.base import Skill


class CostAnalyzerSkill(Skill):
    name = "cost_analyzer"
    category = "FinOps & cost management"
    description = (
        "Answer billing and cost questions about the user's CONNECTED cloud "
        "account using the real spend the suite fetches from Azure Cost "
        "Management. Use this whenever the user asks 'what's my bill', 'how much "
        "did I spend', 'billing for my subscription', 'cost for June', 'which "
        "service costs the most' — live figures are provided, so never ask for "
        "an invoice."
    )
    triggers = [
        "what's the billing for my subscription this month",
        "how much did I spend on Azure in June",
        "which service is costing me the most",
        "break down my cloud costs",
    ]
    parameters = {
        "type": "object",
        "properties": {
            "objective": {
                "type": "string",
                "description": "The billing / cost question to answer.",
            }
        },
        "required": ["objective"],
    }
    system_prompt = (
        "You are a senior FinOps analyst answering billing and cost questions "
        "about a customer's LIVE Azure subscription. You are given the REAL spend "
        "for the requested period — a total plus a by-service breakdown — fetched "
        "read-only from Azure Cost Management. Reason ONLY over the figures "
        "provided; never invent numbers, services or periods, and if a figure is "
        "absent say so plainly.\n\n"
        "METHOD:\n"
        "- Answer the user's actual question first and directly (e.g. the total "
        "for the month they named), using the exact currency shown.\n"
        "- Then give a short by-service breakdown, ordered by cost, and name the "
        "top cost drivers and roughly what share of the total they represent.\n"
        "- Offer a few pragmatic, read-only optimisation ideas tied to the "
        "services that actually dominate the bill (right-sizing, idle/orphaned "
        "resources, reservations/savings plans, storage tiering) — only for "
        "services that appear in the data.\n\n"
        "OUTPUT (Markdown):\n"
        "- A one-line headline with the total spend and period.\n"
        "- A cost-by-service table: Service | Cost | Share.\n"
        "- A short 'Where to look first' list of optimisation opportunities.\n"
        "- If the period shows zero or no charges, state that clearly instead of "
        "speculating.\n\n"
        "GUARDRAILS — READ-ONLY. Suggest optimisations; never present them as "
        "applied and never output commands to run unless explicitly asked."
    )


skill = CostAnalyzerSkill()
