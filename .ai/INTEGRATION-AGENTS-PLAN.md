# InfraLens Integration Plan: n8n · LangChain · LangGraph · Agent Looping

**Status:** Phases 0–4 implemented on `feature/agent-runtime-integration` (flags default off). Phase 5 chat graph scaffolded only.  
**Date:** 2026-09-12  
**Product constraint:** Risk Engine + RBAC + WORKFLOW_SAFE remain source of truth. New agent stacks amplify diagnosis and orchestration — they do not bypass gates.

---

## 0. Executive summary

InfraLens already has the hard parts of an agent platform:

- Chat **plan → skills → synthesise** (`app/chat/orchestrator.py`)
- Solution Architect **critique–revise** pipeline (`app/agents/solution_architect/`)
- Intelligence **workflows → findings → approvals** (`app/intelligence/`)
- Execution **gated write actions** + debug retry (`app/execution/`)
- Optional **Langfuse** tracing; **LangChain/LangGraph deps already installed**

What is missing is deliberate layering:

| Technology | Role in InfraLens | Do not use for |
|------------|-------------------|----------------|
| **LangGraph** | Stateful multi-step agents (Architect first; then chat multi-agent; then debug ReAct) | Nightly diagnose sweeps |
| **LangChain** | Shared LLM client, tools, retrievers, callbacks — glue under graphs | Replacing Postgres memory / redaction |
| **n8n** | Cross-system automation: Slack/Jira/email, human confirm, ticket sync around Approvals & Delivery | Owning Risk Engine or skill execution |
| **Agent looping** | Critique–revise, plan–execute, bounded ReAct — with budgets | Open-ended autonomous apply |

**Highest ROI order:** LangGraph Architect → n8n Approvals/Delivery webhooks → LangChain tool/retriever layer → bounded ReAct on debugger → optional chat graph.

---

## 1. Current system (where value already sits)

```text
Chat orchestrator (custom plan-execute)
    │
    ├─► Diagnose skills (1-shot specialists) ── Azure OpenAI + Langfuse
    └─► Solution Architect (hand-rolled multi-node ≈ graph)
              │
Intelligence RQ worker ── findings + Risk Engine ── Approvals (intent)
Delivery checklist ── architecture job ── Lead accept ── TF plan/apply (human)
Execution layer ── gated CLI/TF ── org executor workers
```

**Already agent-like (keep and upgrade, don’t rip out):**

| Pattern | Location | Today |
|---------|----------|--------|
| Plan–execute–synthesise | `app/chat/orchestrator.py` | Custom JSON planner |
| Critique–revise (≤2) | `app/agents/solution_architect/graph.py` | Sequential Python |
| Human clarify pause | Architect `awaiting_input` + DB | Not LangGraph interrupt |
| Bounded debug retry | `app/execution/debug_loop.py` | MAX_RETRIES=3 |
| Precedent memory | `app/platform/memory.py` | List/search, not LC retriever |
| Checkpointer tables | `graph.setup_checkpointer()` | Best-effort; not wired to live graph |

---

## 2. Value heat map (where each tech pays off)

### Tier A — high value (do these)

1. **LangGraph on Solution Architect**  
   Nodes already map 1:1 (clarify → explore → design → critique → verify → finalize). Checkpointer half-ready. Product differentiator for brownfield design + ADRs → Approvals.

2. **n8n around Approvals + Delivery Lead gates**  
   Slack/Teams/Jira for two-person rule, expiry reminders, stage advance notifications. InfraLens stays authority; n8n is the nervous system to humans/tools outside the app.

3. **LangChain tools + retrievers under Architect (and later chat)**  
   Wrap `tools.py`, provider adapters, engineering memory as Tools/Retrievers. One LLM factory + Langfuse callbacks everywhere.

4. **Bounded ReAct for infra debugger / failed execution**  
   Tool loop only inside validation + Risk Engine budgets. Turns “failed apply” into propose → gate → retry.

### Tier B — medium value (phase 2)

5. **LangGraph for chat Auto multi-agent** when you need mid-plan checkpoint/resume/cancel.  
6. **n8n inbound webhooks** to trigger safe workflows / queue runs (still WORKFLOW_SAFE).  
7. **Agent looping on selected diagnose skills** (e.g. posture → re-check after evidence gap) with hard step/cost caps — not all skills.

### Tier C — low value / avoid

- Replacing Intelligence RQ nightly sweeps with LangGraph or n8n  
- Full ReAct for every chat skill (skills stay one-shot specialists)  
- LangChain memory tables replacing `chat_memories` redaction model  
- Autonomous approval → apply without Lead / gate  
- Generic multi-agent “debate” for findings (conflicts with deterministic Risk Engine)

---

## 3. Target architecture (end state)

```text
┌─────────────────────────────────────────────────────────────┐
│  Frontend (Chat, Dashboard, Delivery, Approvals)            │
└───────────────────────────┬─────────────────────────────────┘
                            │
┌───────────────────────────▼─────────────────────────────────┐
│  FastAPI  — RBAC, Risk Engine, Approvals, Delivery APIs     │
│                                                             │
│  Agent Runtime (new package boundary)                       │
│    LangChain: LLM factory, tools, retrievers, prompts       │
│    LangGraph: Architect graph, optional Chat graph,         │
│               Debug ReAct graph                             │
│    Checkpoints: PostgresSaver (thread_id = run/chat id)     │
│    Observability: Langfuse callbacks + tracing_context      │
└───────┬─────────────────────┬───────────────────┬───────────┘
        │                     │                   │
   RQ intelligence      RQ execution         Webhooks
   (diagnose skills)    (gated writes)            │
        │                     │                   ▼
        ▼                     ▼              ┌─────────┐
   Findings/Approvals   Org executors        │   n8n   │
                                             │ Slack   │
   ◄── inbound decide / run / notify ────────│ Jira    │
                                             │ Email   │
                                             └─────────┘
```

**Invariant:** n8n never decides gate severity or bypasses `min_role`. It calls InfraLens APIs with service credentials.

---

## 4. Area-by-area targeting

### 4.1 Solution Architect — LangGraph + looping (PRIMARY)

**Why:** Already multi-node, human-in-the-loop, ADRs → findings/approvals, delivery checklist waits on it.

**Work:**
1. Replace sequential `graph.py` with LangGraph `StateGraph` using existing `state.py`.
2. Wire `PostgresSaver` with `thread_id = f"architect:{run_id}"`.
3. Map clarify pause to LangGraph interrupt / resume on next user message.
4. Keep critique→design edge with `max_revisions=2` (configurable).
5. Preserve `governance.persist_decisions` → Approvals unchanged.
6. Langfuse: one trace per architecture run; tags `architect`, `project:*`, `delivery:*`.

**Looping techniques here:** critique–revise (exists), optional verify→design on soft fail (new, budgeted).

**Success metrics:** resume after clarify works across API restarts; revision count visible in UI; Langfuse shows node spans.

### 4.2 Approvals & Delivery — n8n (PRIMARY for ops value)

**Why:** Human/two-person gates and Lead accept are where work leaves the product into org process.

**Outbound events (InfraLens → n8n):**
| Event | Emit when | Payload (min) |
|-------|-----------|---------------|
| `approval.created` | Pending approval row | id, project, severity, gate, expiry, deep link |
| `approval.expiring` | Cron &lt; 12h left | id, hours_left |
| `approval.decided` | decide API | id, decision, actor |
| `delivery.stage_changed` | stage transition | run_id, from, to |
| `architecture.ready_for_accept` | Architect finalize | run_id, deep link |
| `execution.failed` | Action failed | action_id, error summary |

**Inbound (n8n → InfraLens):**
| Action | Maps to existing API | Guard |
|--------|----------------------|-------|
| Approve / reject | `POST /api/approvals/{id}/decide` | Same RBAC as UI; service account + audit |
| Run workflow | `POST /api/workflows/{id}/run` | WORKFLOW_SAFE only |
| Advance delivery (notify-only or Lead-gated) | delivery transition | Lead role required |
| Ack finding | findings PATCH | Non-destructive |

**Implementation shape:**
- `app/integrations/webhooks.py` — signed outbound HMAC webhooks + optional n8n URL from Settings
- `app/api/routes_integrations.py` — documented inbound routes + API key / m2m auth
- Sample n8n workflow JSON in `docs/integrations/n8n/` (Slack notify + button → decide)

**Success metrics:** time-to-first-human-response on high gate; zero gate bypass in audit log.

### 4.3 Chat orchestrator — LangChain now, LangGraph later

**Phase 1 (LangChain only):**
- Shared `get_chat_llm()` mirroring architect LLM + Langfuse handler
- Tool wrappers for “forced skill” path only if useful; keep skill registry contract
- Retriever for engineering memory + chat facts into planner context

**Phase 2 (LangGraph optional):**
- Nodes: `plan` → `skill_i` → `synthesise` with checkpoint per chat turn
- Only if product needs: pause mid-plan, cancel remaining skills, retry one skill

**Do not:** turn every diagnose skill into a ReAct agent.

### 4.4 Intelligence workflows — leave RQ; add hooks only

**Keep:** `worker.run_workflow` sequential read-only skills + `build_findings`.

**Add:**
- Outbound webhook on run completed / findings saved
- Optional n8n cron that calls “Run now” instead of duplicating skill logic in n8n
- Later: skill-level “evidence insufficient → one re-ask loop” behind a feature flag and cost cap

### 4.5 Execution / debugger — bounded ReAct (HIGH for write path)

**Target:** `app/execution/debug_loop.py` + `chat_actions.py`

**Graph sketch:**
```text
observe_failure → propose_fix (LLM+tools) → validate_action → 
  [gate] → execute → observe → 
  (success | retry&lt;N | escalate_approval)
```

**Hard stops:** MAX_STEPS, MAX_RETRIES, blast_radius ceiling, always Risk Engine before execute.

### 4.6 Memory & retrieval — LangChain adapters, Postgres truth

- Retrievers over `platform/memory.py`, findings identities, prior ADRs
- Feed Approvals UI “Precedent” and Architect critique (already partially there)
- Never store secrets in vector store; keep redaction rules from `chat_memory.py`

### 4.7 Observability — non-negotiable

Every new graph/tool path must:
- Use `observability.tracing_context`
- Attach Langfuse session = `chat_id` | `workflow-run:*` | `architect:*`
- Tag feature: `architect` | `intelligence` | `execution` | `n8n`

---

## 5. Agent looping techniques — when to use which

| Technique | Use in InfraLens | Budget |
|-----------|------------------|--------|
| **Plan–execute–synthesise** | Chat Auto (exists) | Max N skills per turn |
| **Critique–revise** | Architect design (exists) | max_revisions=2 |
| **Human-in-the-loop interrupt** | Architect clarify; Approvals; Delivery Lead | Unlimited wall time, gated resume |
| **Bounded ReAct** | Debugger / failed TF or CLI | max_steps=5–8, max_retries=3 |
| **Verify–repair** | Architect verify soft-fail → design | 1 repair pass |
| **Self-consistency / debate** | Avoid for gated findings | — |
| **Open-ended autonomous loop** | Never for apply/prod writes | — |

**Loop policy object (add once, reuse everywhere):**
```text
AgentLoopPolicy:
  max_steps, max_revisions, max_tool_calls
  max_tokens / max_cost_usd (optional)
  allowed_tools[]
  require_gate_before: ["execute", "write", "apply"]
  on_budget_exhausted: "escalate" | "stop_with_summary"
```

---

## 6. Phased roadmap

### Phase 0 — Foundations (1–1.5 weeks)
- Document agent runtime boundaries in `.ai/ARCHITECTURE.md`
- Single LLM factory module (`app/agents/runtime/llm.py`) wrapping Azure + Langfuse
- Webhook event schema + Settings fields (`N8N_WEBHOOK_URL`, `WEBHOOK_HMAC_SECRET`)
- Feature flags: `architect_langgraph`, `n8n_webhooks`, `debug_react`

### Phase 1 — Architect → LangGraph (2–3 weeks) **highest product leverage**
- Port `solution_architect/graph.py` to StateGraph
- Checkpoint + interrupt/resume
- Parity tests vs current pipeline outputs (ADR shape, gate decisions)
- Delivery checklist continues to poll same APIs

### Phase 2 — n8n integration (1–2 weeks) **highest org/process leverage**
- Outbound events for approvals + delivery + architecture ready
- Sample Slack + Jira workflows
- Inbound decide/run with m2m auth + audit trail
- Dashboard: “Integrations” status (webhook last success)

### Phase 3 — LangChain tools/retrievers (1–2 weeks)
- Toolize architect `tools.py` + memory retriever
- Precedent enrichment on Approvals cards (stronger than today)
- Shared prompt templates via existing `prompts.py` / Langfuse

### Phase 4 — Bounded ReAct debugger (2 weeks)
- LangGraph ReAct for execution failures only
- UI: show loop steps in action detail / chat
- Hard policy enforcement + Langfuse spans per tool call

### Phase 5 — Optional chat LangGraph (1–2 weeks, only if needed)
- Checkpointed multi-skill chat plans
- Cancel / resume remaining skills

### Phase 6 — Harden & scale
- Cost dashboards (Langfuse)
- Per-org n8n credentials
- Load tests on webhook fan-out
- Docs for customers: “bring your own n8n”

---

## 7. Suggested package layout (when implementing)

```text
app/agents/
  runtime/
    llm.py              # shared AzureChatOpenAI + Langfuse
    policies.py         # AgentLoopPolicy
    tools_base.py       # LC tool adapters
  solution_architect/   # existing → LangGraph compile here
  chat_graph/           # phase 5 optional
  debug_graph/          # phase 4
app/integrations/
  webhooks.py           # outbound signed events
  n8n_schemas.py        # event payloads
app/api/routes_integrations.py
docs/integrations/n8n/
  approvals-slack.json
  delivery-notify.json
```

---

## 8. Risks & guardrails

| Risk | Mitigation |
|------|------------|
| Agents bypass Risk Engine | Gates only in FastAPI service layer; graphs call services, never raw executors |
| n8n becomes shadow control plane | Inbound APIs enforce RBAC + audit; no “admin webhook” that skips min_role |
| Cost blowups from loops | AgentLoopPolicy + Langfuse cost alerts |
| LangGraph rewrite regressions | Golden tests on Architect outputs; feature flag rollback to sequential graph |
| Checkpoint/PII in Postgres | Reuse redaction; don’t checkpoint raw secrets |
| Duplicate orchestration (RQ + n8n + graph) | Clear ownership: RQ=diagnose batch, Graph=interactive agent, n8n=external human/systems |

---

## 9. What to tell stakeholders (one slide)

> We will not sprinkle agents everywhere. We upgrade the **Solution Architect** to a real LangGraph stateful agent, connect **Approvals/Delivery** to the org via **n8n**, share **LangChain** tooling/memory under those graphs, and add **bounded ReAct** only where failed changes need repair — always behind InfraLens Risk Engine and Lead gates.

---

## 10. Recommended start Monday (execution checklist)

1. Land Phase 0 LLM factory + feature flags (no behavior change).  
2. Spike: compile Architect StateGraph behind `architect_langgraph=false` default.  
3. Parallel: design webhook payload OpenAPI + one Slack n8n workflow against staging Approvals.  
4. Demo gate: Architect resume-after-clarify + Slack approval ping on one high finding.

---

## 11. Explicit non-goals (next 90 days)

- Replacing diagnose skill implementations with LangChain agents  
- Running Terraform apply from n8n without Lead path  
- Multi-agent debate for severity scoring  
- Replacing Langfuse with another observability stack mid-migration  
