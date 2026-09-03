"""Clarify → explore → design → critique → verify → finalize."""
from __future__ import annotations

import json
from typing import Any, Callable, Iterator, Optional

from app.core import (
    azure_client,
    config as app_config,
)
from app.agents.solution_architect import governance, prompts, tools
from app.agents.solution_architect.state import ArchitectState, empty_state, infer_tier
from app.intelligence import risk_engine

Emit = Callable[[dict[str, Any]], None]
RECURSION_LIMIT = 12


def _json_chat(system: str, user: str, name: str) -> dict[str, Any]:
    if not app_config.get_azure_config().configured:
        raise RuntimeError(
            "Azure OpenAI is not configured. Open Settings and add the platform "
            "endpoint and API key."
        )
    try:
        completion = azure_client.chat(
            [
                {"role": "system", "content": system},
                {"role": "user", "content": user[:24000]},
            ],
            temperature=0.2,
            response_format={"type": "json_object"},
            name=name,
        )
        content = completion.choices[0].message.content or "{}"
        parsed = json.loads(content)
    except Exception as exc:
        raise RuntimeError(f"Azure OpenAI request failed ({name}): {exc}") from exc
    if not isinstance(parsed, dict):
        raise RuntimeError(f"Azure OpenAI returned a non-object JSON response ({name})")
    return parsed


def _node_prompt(name: str, state: ArchitectState) -> str:
    return prompts.node_prompt(name, tier=state.get("tier") or "T1", mode=state.get("mode") or "greenfield")


def clarify(state: ArchitectState, emit: Emit) -> ArchitectState:
    emit({"type": "status", "text": "Clarifying the ask"})
    parsed = _json_chat(
        _node_prompt("architect-clarify", state),
        f"Objective:\n{state.get('objective')}\n\nConstraints:\n{state.get('constraints')}\n\n"
        f"Seed:\n{state.get('seed_context')}\n\nPrior Q&A:\n{state.get('clarifying_qa')}",
        "architect-clarify",
    )
    state["objective"] = str(parsed.get("objective") or state.get("objective") or "")
    state["constraints"] = str(parsed.get("constraints") or state.get("constraints") or "")
    tier = parsed.get("tier") or infer_tier(state.get("objective") or "")
    if tier in {"T1", "T2", "T3"}:
        state["tier"] = tier
    assumptions = parsed.get("assumptions") if isinstance(parsed.get("assumptions"), list) else []
    state["assumptions"] = [str(item) for item in assumptions]
    needs_question = bool(parsed.get("needs_question")) and (state.get("tier") in {"T2", "T3"})
    question = str(parsed.get("question") or "").strip()
    if needs_question and question and not state.get("plan_only"):
        state["awaiting_input"] = True
        state["pending_question"] = question
        state["reply"] = question
        return state
    if question and state.get("plan_only"):
        state["assumptions"] = list(state.get("assumptions") or []) + [question]
    state["awaiting_input"] = False
    state["pending_question"] = ""
    return state


def explore(state: ArchitectState, emit: Emit) -> ArchitectState:
    emit({"type": "status", "text": "Exploring the environment"})
    project_id = state.get("project_id") or ""
    inventory = tools.get_cloud_inventory(project_id)
    empty = tools.inventory_is_empty(inventory)
    state["mode"] = "greenfield" if empty else "brownfield"
    emit({"type": "status", "text": "Reading mapped repository and live inventory"})
    code = tools.get_code_artifacts(project_id)
    from app.agents.solution_architect.discovery import discover

    state["discovery"] = discover(
        project_id=project_id,
        inventory=inventory,
        code=code,
        objective=state.get("objective") or "",
        seed=state.get("seed_context") or "",
    )
    evidence = [inventory, code, tools.search_precedent(project_id)]
    if state.get("seed_context"):
        evidence.insert(0, str(state.get("seed_context"))[:12000])
    if state.get("tier") in {"T2", "T3"}:
        emit({"type": "status", "text": "Gathering cost and code evidence"})
        evidence.append(tools.get_cost_report(project_id, state.get("objective") or ""))
        if "pci" in (state.get("objective") or "").lower() or "compliance" in (state.get("constraints") or "").lower():
            evidence.append(
                tools.run_skill(
                    "compliance_mapper",
                    {
                        "objective": state.get("objective") or "",
                        "task": state.get("objective") or "",
                        "controls": inventory,
                        "framework": "pci-dss",
                    },
                )
            )
        if not empty:
            evidence.append(
                tools.run_skill(
                    "drift_auditor",
                    {"objective": state.get("objective") or "", "task": state.get("objective") or "", "operating_policy": ""},
                )
            )
    parsed = _json_chat(
        _node_prompt("architect-explore", state),
        (
            "Discovery:\n"
            f"{json.dumps(state.get('discovery') or {}, default=str)[:4000]}\n\n"
            + "\n\n".join(evidence)
        )[:20000],
        "architect-explore",
    )
    if parsed.get("mode") in {"greenfield", "brownfield"}:
        state["mode"] = parsed["mode"]
    if parsed.get("tier") in {"T1", "T2", "T3"}:
        # Evidence may raise the tier, never silently drop T3.
        current = state.get("tier") or "T1"
        proposed = parsed["tier"]
        if proposed > current or current == "T1":
            state["tier"] = proposed
    state["exploration_notes"] = str(parsed.get("notes") or inventory[:4000])
    return state


def design(state: ArchitectState, emit: Emit) -> ArchitectState:
    emit({"type": "status", "text": "Designing against the rubric"})
    lld = ""
    if state.get("tier") in {"T2", "T3"}:
        emit({"type": "status", "text": "Drafting resource-level LLD"})
        lld = tools.design_resource_plan(
            {
                "objective": state.get("objective") or "",
                "constraints": state.get("constraints") or "",
                "task": state.get("objective") or "",
                "operating_policy": "Design only. Do not claim infrastructure changed.",
            }
        )
    parsed = _json_chat(
        _node_prompt("architect-design", state),
        f"Discovery:\n{json.dumps(state.get('discovery') or {}, default=str)[:4000]}\n\n"
        f"Notes:\n{state.get('exploration_notes')}\n\nLLD:\n{lld[:8000]}\n\n"
        f"Assumptions:\n{state.get('assumptions')}",
        "architect-design",
    )
    candidates = parsed.get("candidates") if isinstance(parsed.get("candidates"), list) else []
    if not candidates:
        from app.agents.solution_architect.model import fallback_candidates

        candidates = fallback_candidates(state)
    state["candidates"] = candidates
    state["mermaid"] = str(parsed.get("mermaid") or mermaid_from_state(state))
    state["hld"] = str(parsed.get("hld_outline") or "")
    return state


def critique(state: ArchitectState, emit: Emit) -> ArchitectState:
    emit({"type": "status", "text": "Critiquing the design"})
    gated = []
    for item in state.get("candidates") or []:
        preview = tools.preview_gate(
            str(item.get("risk_class") or "config_code_change"),
            str(item.get("blast_radius") or "medium"),
        )
        gated.append({**item, "preview_gate": preview, "justified": bool(item.get("justified"))})
    precedent = tools.search_precedent(state.get("project_id") or "")
    parsed = _json_chat(
        _node_prompt("architect-critique", state),
        f"Candidates:\n{json.dumps(gated, default=str)[:12000]}\n\nPrecedent:\n{precedent}",
        "architect-critique",
    )
    if isinstance(parsed.get("candidates"), list) and parsed["candidates"]:
        state["candidates"] = parsed["candidates"]
    else:
        state["candidates"] = gated
    state["critique_notes"] = str(parsed.get("notes") or "")
    revise = bool(parsed.get("revise")) or governance.high_gate_unjustified(state["candidates"])
    if revise and int(state.get("revision_count") or 0) < 2 and state.get("tier") in {"T2", "T3"}:
        state["revision_count"] = int(state.get("revision_count") or 0) + 1
        for item in state["candidates"]:
            if (item.get("preview_gate") or {}).get("gate") == "two_person":
                item["risk_class"] = "config_code_change"
                item["blast_radius"] = "medium"
                item["change"] = f"Staged alternative: {item.get('change')}"
                item["justified"] = True
        emit({"type": "status", "text": "Revising toward a reversible design"})
        return design(state, emit)
    return state


def verify(state: ArchitectState, emit: Emit) -> ArchitectState:
    emit({"type": "status", "text": "Senior architect verification"})
    parsed = _json_chat(
        _node_prompt("architect-verify", state),
        f"Candidates:\n{json.dumps(state.get('candidates') or [], default=str)[:12000]}\n"
        f"Critique:\n{state.get('critique_notes')}\nMermaid:\n{state.get('mermaid')}\n"
        f"plan_only={state.get('plan_only')}",
        "architect-verify",
    )
    state["verify_notes"] = str(parsed.get("notes") or "Signed off.")
    decisions = parsed.get("decisions") if isinstance(parsed.get("decisions"), list) else []
    if not decisions:
        recommended = [item for item in (state.get("candidates") or []) if item.get("recommended")]
        source = recommended or (state.get("candidates") or [])
        decisions = [
            {
                "title": item.get("title") or "Architecture decision",
                "context": state.get("exploration_notes") or state.get("objective") or "",
                "options_considered": item.get("options_considered") or [],
                "decision": item.get("change") or item.get("title") or "",
                "consequences": item.get("consequences") or "",
                "risk_class": item.get("risk_class") or "config_code_change",
                "blast_radius": item.get("blast_radius") or "low",
                "severity": "low" if state.get("tier") == "T1" else "medium",
                "recommended_action": item.get("change") or "",
            }
            for item in source[: (1 if state.get("tier") == "T1" else 6)]
        ]
    state["decisions"] = [
        {
            **item,
            "risk_class": risk_engine.normalize_action_class(item.get("risk_class")),
            "blast_radius": risk_engine.normalize_blast_radius(item.get("blast_radius")),
        }
        for item in decisions
        if isinstance(item, dict)
    ]
    steps = parsed.get("plan_steps") if isinstance(parsed.get("plan_steps"), list) else []
    state["plan_steps"] = [
        {"skill": str(step.get("skill") or ""), "objective": str(step.get("objective") or "")}
        for step in steps
        if step.get("skill") and step.get("skill") != "solution_architect"
    ]
    if not state["plan_steps"]:
        state["plan_steps"] = [
            {
                "skill": "infrastructure_architect",
                "objective": f"Produce an LLD for: {state.get('objective')}",
            }
        ]
    if parsed.get("hld"):
        state["hld"] = str(parsed["hld"])
    return state


def finalize(state: ArchitectState, emit: Emit) -> ArchitectState:
    emit({"type": "status", "text": "Recording decisions"})
    run_kwargs = dict(
        thread_id=state.get("thread_id") or "",
        project_id=state.get("project_id") or "",
        user_id=state.get("user") or "",
        objective=state.get("objective") or "",
        source=state.get("source") or "chat",
        tier=state.get("tier") or "T1",
        mode=state.get("mode") or "greenfield",
        checkpoint=dict(state),
    )
    run_id = governance.upsert_run(status="running", **run_kwargs)
    try:
        try:
            gated = governance.persist_decisions(
                run_id=run_id,
                project_id=state.get("project_id") or "",
                decisions=state.get("decisions") or [],
            )
        except Exception:
            gated = list(state.get("decisions") or [])
        from app.agents.solution_architect.model import build_architecture

        state["architecture"] = build_architecture(state)
        try:
            from app.platform.engineering.generate import apply_architect_result

            delivery_id = ""
            thread = str(state.get("thread_id") or "")
            if thread.startswith("delivery:"):
                delivery_id = thread.split(":", 1)[-1]
            apply_architect_result(
                dict(state),
                run_id=run_id,
                gated=gated,
                delivery_run_id=delivery_id,
            )
        except Exception:
            if state.get("source") == "delivery":
                raise
        state["hld"] = _render_hld(state, gated)
        state["reply"] = state["hld"]
        governance.upsert_run(status="succeeded", **{**run_kwargs, "checkpoint": dict(state)})
        return state
    except Exception:
        try:
            governance.upsert_run(status="failed", **{**run_kwargs, "checkpoint": dict(state)})
        except Exception:
            pass
        raise


def mermaid_from_state(state: ArchitectState) -> str:
    from app.agents.solution_architect.model import mermaid_from_discovery

    return mermaid_from_discovery(state)


def _default_mermaid(state: ArchitectState) -> str:
    return mermaid_from_state(state)


def _render_hld(state: ArchitectState, gated: list[dict[str, Any]]) -> str:
    assumptions = state.get("assumptions") or []
    mermaid = state.get("mermaid") or mermaid_from_state(state)
    architecture = state.get("architecture") if isinstance(state.get("architecture"), dict) else {}
    analysis = architecture.get("analysis") if isinstance(architecture.get("analysis"), dict) else {}
    lines = [
        f"# Architecture proposal ({state.get('tier')}, {state.get('mode')})",
        "",
        state.get("hld") or state.get("objective") or "",
        "",
        "## Assumptions & open questions",
    ]
    if assumptions:
        lines.extend(f"- {item}" for item in assumptions)
    else:
        lines.append("- None recorded.")
    if architecture.get("cloud"):
        lines.extend(
            [
                "",
                "## Recommended platform",
                f"- Cloud: {architecture.get('cloud')}",
                f"- Mode: {architecture.get('mode') or state.get('mode')}",
                f"- IaC: {architecture.get('iac_strategy') or 'Terraform via PR'}",
            ]
        )
    components = architecture.get("components") or []
    if components:
        lines.extend(["", "## Components"])
        for item in components:
            lines.append(
                f"- **{item.get('name')}** ({item.get('service')}): {item.get('purpose')}"
            )
            if item.get("reason") and item.get("reason") != item.get("purpose"):
                lines.append(f"  - Why: {item.get('reason')}")
    if analysis:
        lines.extend(["", "## Why this design"])
        for key in ("brownfield", "security", "scaling", "cost", "availability"):
            value = analysis.get(key)
            if isinstance(value, list):
                lines.append(f"### {key.replace('_', ' ').title()}")
                lines.extend(f"- {item}" for item in value)
            elif value:
                lines.append(f"- {value}")
    lines.extend(["", "## Context diagram", "", "```mermaid", mermaid.strip(), "```", "", "## ADRs"])
    for item in gated or state.get("decisions") or []:
        lines.append(f"### {item.get('title')}")
        lines.append(item.get("decision") or item.get("change") or "")
        if item.get("consequences"):
            lines.append(f"_Why: {item.get('consequences')}_")
        if item.get("gate") or item.get("gate_decision"):
            lines.append(f"_Gate: {item.get('gate') or item.get('gate_decision')}_")
        lines.append("")
    if state.get("verify_notes"):
        lines.extend(["## Senior architect verification", state["verify_notes"], ""])
    if state.get("critique_notes"):
        lines.extend(["## Critique", state["critique_notes"], ""])
    return "\n".join(lines).strip()


def run_pipeline(state: ArchitectState, emit: Optional[Emit] = None) -> ArchitectState:
    sink: Emit = emit or (lambda _event: None)
    paused = governance.load_paused(state.get("thread_id") or "")
    if paused and not state.get("plan_only"):
        answer = state.get("objective") or ""
        state = empty_state(**{k: v for k, v in paused.items() if k != "_run_id"})
        qa = list(state.get("clarifying_qa") or [])
        qa.append({"q": str(paused.get("pending_question") or ""), "a": answer})
        state["clarifying_qa"] = qa
        state["awaiting_input"] = False
        state["pending_question"] = ""
        state = explore(state, sink)
        steps = (design, critique, verify, finalize)
    else:
        state = clarify(state, sink)
        if state.get("awaiting_input"):
            governance.upsert_run(
                thread_id=state.get("thread_id") or "",
                project_id=state.get("project_id") or "",
                user_id=state.get("user") or "",
                objective=state.get("objective") or "",
                source=state.get("source") or "chat",
                tier=state.get("tier") or "T1",
                mode=state.get("mode") or "greenfield",
                status="awaiting_input",
                pending_question=state.get("pending_question") or "",
                checkpoint=dict(state),
            )
            return state
        steps = (explore, design, critique, verify, finalize)
    for step in steps:
        state = step(state, sink)
        if state.get("awaiting_input"):
            return state
    return state


def _initial_state(args: dict[str, Any], chat_id: str) -> ArchitectState:
    objective = str(args.get("objective") or args.get("task") or args.get("message") or "")
    project_id = str(args.get("project_id") or "")
    seed = str(args.get("live_environment") or args.get("seed_context") or args.get("conversation_memory") or "")
    try:
        from app.platform.engineering.context import architect_seed

        extra = architect_seed(project_id, seed)
        if extra:
            seed = extra
    except Exception:
        pass
    return empty_state(
        objective=objective,
        project_id=project_id,
        user=str(args.get("user") or args.get("user_id") or ""),
        constraints=str(args.get("constraints") or args.get("operating_policy") or ""),
        seed_context=seed,
        tier=infer_tier(objective),
        plan_only=bool(args.get("plan_only")),
        source="delivery" if args.get("source") == "delivery" else "chat",
        thread_id=chat_id or str(args.get("thread_id") or ""),
        messages=list(args.get("messages") or []),
    )


def stream_architect(args: dict[str, Any], *, chat_id: str) -> Iterator[dict[str, Any]]:
    import threading
    from queue import SimpleQueue

    events: SimpleQueue = SimpleQueue()
    holder: dict[str, Any] = {}

    def emit(event: dict[str, Any]) -> None:
        events.put(event)

    def runner() -> None:
        try:
            holder["state"] = run_pipeline(_initial_state(args, chat_id), emit)
        except Exception as exc:  # noqa: BLE001
            holder["error"] = exc
        finally:
            events.put(None)

    thread = threading.Thread(target=runner, name="architect-stream", daemon=True)
    thread.start()
    while True:
        item = events.get()
        if item is None:
            break
        yield item
    thread.join(timeout=2)
    if holder.get("error"):
        raise holder["error"]
    state = holder.get("state") or {}
    if state.get("awaiting_input"):
        question = state.get("pending_question") or state.get("reply") or "Need one clarification before designing."
        yield {"type": "delta", "text": question}
        yield {"type": "final", "mode": "agent", "reply": question, "skills_used": ["solution_architect"], "tier": state.get("tier"), "architect_mode": state.get("mode")}
        return
    reply = state.get("reply") or state.get("hld") or ""
    yield {"type": "delta", "text": reply}
    payload: dict[str, Any] = {
        "type": "final",
        "mode": "plan" if state.get("plan_only") else "agent",
        "reply": reply,
        "skills_used": ["solution_architect"],
        "tier": state.get("tier"),
        "architect_mode": state.get("mode"),
    }
    if state.get("plan_only"):
        payload["plan"] = state.get("plan_steps") or []
    payload["architecture"] = state.get("architecture") or {}
    payload["mermaid"] = state.get("mermaid") or ""
    yield payload


def invoke_architect(args: dict[str, Any], *, chat_id: str = "") -> dict[str, Any]:
    final: dict[str, Any] = {}
    for event in stream_architect(args, chat_id=chat_id):
        if event.get("type") == "final":
            final = event
    return final


def setup_checkpointer() -> None:
    """Best-effort LangGraph Postgres checkpoint tables."""
    try:
        from langgraph.checkpoint.postgres import PostgresSaver
        from psycopg_pool import ConnectionPool

        from app.core.db import get_database_url

        url = get_database_url().replace("postgresql+psycopg2://", "postgresql://").replace(
            "postgresql+psycopg://", "postgresql://"
        )
        pool = ConnectionPool(conninfo=url, kwargs={"autocommit": True, "prepare_threshold": 0}, max_size=4)
        PostgresSaver(pool).setup()
    except Exception:
        return
