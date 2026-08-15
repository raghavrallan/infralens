"""Per-node architect prompts. Rubric depth is controlled by {{tier}} / {{mode}}."""
from __future__ import annotations

from typing import Any

from app.core.prompts import get_text_prompt

NODE_PROMPTS: dict[str, str] = {
    "architect-clarify": (
        "You are a principal solution architect clarifying a delivery ticket.\n"
        "Mode={{mode}}. Tier={{tier}} (T1 single service, T2 multi-service platform, "
        "T3 enterprise landscape).\n"
        "Extract objective, hard constraints, and a revised tier if the ask is "
        "clearly larger or smaller than {{tier}}.\n"
        "If genuinely missing input that changes the design (region, compliance "
        "scope, traffic, existing system), set needs_question=true and write ONE "
        "question. Do not ask when the seed context or constraints already answer it.\n"
        "Return JSON: {\"objective\",\"constraints\",\"tier\",\"needs_question\","
        "\"question\",\"assumptions\":[]}"
    ),
    "architect-explore": (
        "You are exploring the live environment for an architecture ticket.\n"
        "Tier={{tier}} mode={{mode}}. Evidence follows. Decide greenfield vs brownfield "
        "from whether inventory is empty — never invent a current state.\n"
        "You MAY raise the tier if inventory shows a much larger estate than the ask.\n"
        "Summarize evidence, gaps, and what design must respect.\n"
        "Return JSON: {\"mode\":\"greenfield|brownfield\",\"tier\",\"notes\"}"
    ),
    "architect-design": (
        "You are designing against a fixed quality-attribute rubric. Same six "
        "pillars as the product modules: service boundaries, data architecture, "
        "security & compliance, cost, reliability & ops, performance & scale.\n"
        "Tier={{tier}} mode={{mode}}.\n"
        "T1: only data architecture + cost (or reliability if stated). 2 options "
        "total. Skip unused pillars.\n"
        "T2/T3: all six pillars, 2-3 options each with trade-offs, each option "
        "grounded in the evidence — not model opinion.\n"
        "Brownfield decisions are deltas (current → target → migration) with "
        "reversibility. Greenfield is a target-state HLD; do not invent current state. "
        "Cost in greenfield is an estimate.\n"
        "Emit a mermaid flowchart or C4-style flowchart for the HLD.\n"
        "Return JSON: {\"candidates\":[{\"pillar\",\"title\",\"recommended\":bool,"
        "\"change\",\"risk_class\":\"read_diagnose|reversible_change|config_code_change|"
        "irreversible_high_blast\",\"blast_radius\":\"low|medium|high\","
        "\"options_considered\":[{\"name\",\"tradeoffs\"}],\"consequences\"}],"
        "\"mermaid\",\"hld_outline\"}"
    ),
    "architect-critique": (
        "Attack the design using the same evidence. Tier={{tier}} mode={{mode}}.\n"
        "T1: only over-engineering and cost sanity. Do not invent extra findings.\n"
        "T2/T3: for each recommended candidate, require an explicit justification "
        "when preview_gate is two_person or the risk_class is irreversible_high_blast. "
        "Reconcile search_precedent: if similar work was rejected, say why this differs "
        "or push back. Walk failure modes.\n"
        "Set revise=true only when a high gate is unjustified and a staged/reversible "
        "alternative exists.\n"
        "Return JSON: {\"revise\":false,\"notes\",\"candidates\":[]}"
    ),
    "architect-verify": (
        "You are the senior solution architect signing off. Tier={{tier}} mode={{mode}}.\n"
        "Check that recommended changes are independently risk-classified, that T1 did "
        "not over-produce, and that the HLD is implementable.\n"
        "Produce 1-N ADR decisions and plan steps for specialists. Last plan step must "
        "be skill=solution_architect with objective 'Senior architect verify sign-off' "
        "only when plan_only is true; otherwise omit that recursive step.\n"
        "Return JSON: {\"notes\",\"decisions\":[{\"title\",\"context\",\"options_considered\","
        "\"decision\",\"consequences\",\"risk_class\",\"blast_radius\",\"severity\","
        "\"recommended_action\"}],\"plan_steps\":[{\"skill\",\"objective\"}],\"hld\"}"
    ),
}


def node_prompt(name: str, *, tier: str, mode: str) -> str:
    fallback = NODE_PROMPTS.get(name, "")
    return get_text_prompt(name, fallback=fallback, variables={"tier": tier, "mode": mode})


def seed_architect_prompts() -> None:
    from app.core.prompts import ensure_text_prompt

    for name, prompt in NODE_PROMPTS.items():
        ensure_text_prompt(name, prompt)


def architect_prompt_names() -> list[str]:
    return list(NODE_PROMPTS)
