"""Normalize a skill's free-form analysis into discrete, gated findings.

A diagnose skill returns Markdown (or JSON) written for a human. The dashboard
needs discrete findings with a severity, an affected resource and a recommended
action. A short extraction pass turns the analysis into that structure; if the
model is unavailable or returns nothing usable, the whole analysis becomes a
single finding so a run never silently produces nothing.
"""
import json
from typing import Any

from app import azure_client
from app.intelligence import risk_engine
from app.skills import blast_radius_for, remediation_class_for

_SEVERITIES = ("critical", "high", "medium", "low")

_EXTRACT_SYSTEM_PROMPT = (
    "You convert a DevSecOps analysis into a list of discrete findings for a "
    "dashboard. Read the analysis and extract each distinct issue, risk or "
    "recommendation as its own finding. Do NOT invent anything not supported by "
    "the analysis; if the analysis is clean, return an empty list.\n\n"
    "Respond ONLY with JSON of the form:\n"
    '{"findings": [{"title": "<short imperative title>", '
    '"severity": "critical|high|medium|low", '
    '"resource": "<affected resource / file / repo, or empty>", '
    '"category": "<short area, e.g. Security, Cost, Reliability, Drift>", '
    '"evidence": "<1-2 sentences citing the specific detail from the analysis>", '
    '"recommended_action": "<the concrete change that would resolve it>"}]}'
)


def _severity_from_text(text: str) -> str:
    """Best-effort severity from free text (mirrors the chat UI heuristic)."""
    low = text.lower()
    for sev in _SEVERITIES:
        if sev in low:
            return sev
    return "low"


def _clean_severity(value: Any) -> str:
    sev = str(value or "").strip().lower()
    return sev if sev in _SEVERITIES else "low"


def _clean_title(raw: str) -> str:
    """Make a human title, recovering readable text if the model echoed JSON."""
    title = (raw or "").strip()
    if title[:1] in ("{", "[") and ("summary" in title or "title" in title):
        try:
            data = json.loads(title)
        except (ValueError, json.JSONDecodeError):
            data = None
        if isinstance(data, dict):
            for key in ("title", "summary", "headline", "finding"):
                value = data.get(key)
                if isinstance(value, str) and value.strip():
                    title = value.strip()
                    break
    title = title.lstrip("#").strip().strip('"')
    return title[:400]


def _extract_structured(skill: str, output: str, objective: str) -> list[dict[str, Any]]:
    """Ask the model to split the analysis into discrete findings."""
    try:
        completion = azure_client.chat(
            messages=[
                {"role": "system", "content": _EXTRACT_SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": (
                        f"Skill: {skill}\nObjective: {objective}\n\n"
                        f"Analysis:\n{output}"
                    ),
                },
            ],
            temperature=0.0,
            response_format={"type": "json_object"},
        )
        parsed = json.loads(completion.choices[0].message.content or "{}")
    except Exception:  # noqa: BLE001 - fall back to a single finding on any failure
        return []
    items = parsed.get("findings")
    if not isinstance(items, list):
        return []
    findings: list[dict[str, Any]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        title = _clean_title(str(item.get("title", "")))
        if not title:
            continue
        findings.append(
            {
                "title": title,
                "severity": _clean_severity(item.get("severity")),
                "resource": str(item.get("resource", "")).strip()[:400],
                "category": str(item.get("category", "")).strip()[:120],
                "evidence": str(item.get("evidence", "")).strip(),
                "recommended_action": str(item.get("recommended_action", "")).strip(),
            }
        )
    return findings


def _fallback_finding(skill: str, output: str, objective: str) -> dict[str, Any]:
    summary = output.strip().splitlines()
    title = next((line.strip("# ").strip() for line in summary if line.strip()), "")
    return {
        "title": _clean_title(title) or (objective or f"{skill} summary")[:400],
        "severity": _severity_from_text(output),
        "resource": "",
        "category": "",
        "evidence": output.strip()[:2000],
        "recommended_action": "",
    }


def _apply_gate(skill: str, module: str, finding: dict[str, Any], environment: str) -> dict[str, Any]:
    """Attach the Risk Engine gate to a finding based on its remediation."""
    action_class = remediation_class_for(skill)
    blast = risk_engine.blast_radius_from_severity(
        blast_radius_for(skill), finding["severity"]
    )
    decision = risk_engine.classify(action_class, blast, environment)  # type: ignore[arg-type]
    return {
        **finding,
        "skill": skill,
        "module": module,
        "risk_class": action_class,
        "blast_radius": blast,
        "gate_decision": decision.gate,
        "gate_label": decision.label,
        "gate_rationale": decision.rationale,
    }


def build_findings(
    skill: str,
    module: str,
    output: str,
    objective: str,
    environment: str = "prod",
) -> list[dict[str, Any]]:
    """Turn one skill run's output into a list of gated finding dicts."""
    if not output or not output.strip():
        return []
    extracted = _extract_structured(skill, output, objective)
    if not extracted:
        extracted = [_fallback_finding(skill, output, objective)]
    return [_apply_gate(skill, module, item, environment) for item in extracted]
