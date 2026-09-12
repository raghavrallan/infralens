# SESSION.md

Last session: 2026-09-12  
Branch: `feature/agent-runtime-integration`

## Purpose

Implement n8n + LangChain + LangGraph + agent looping plan phase by phase.

## Done this session

- Phase 0: `app/agents/runtime/` (LLM factory, flags, policies), webhook schema
- Phase 1: LangGraph architect (`lg_graph.py`) behind `ARCHITECT_LANGGRAPH` (default off); sequential path still default
- Phase 2: outbound webhooks + `/api/integrations/*` + sample n8n JSON
- Phase 3: LC tools + PrecedentRetriever wired into architect search_precedent
- Phase 4: bounded debug ReAct facade (`DEBUG_REACT_ENABLED`)
- Phase 5: chat graph scaffold only (`CHAT_LANGGRAPH`)
- Tests: `tests/test_agent_runtime.py` green

## Enable in .env when ready

```
ARCHITECT_LANGGRAPH=true
N8N_WEBHOOKS_ENABLED=true
N8N_WEBHOOK_URL=...
WEBHOOK_HMAC_SECRET=...
INTEGRATIONS_API_KEY=...
DEBUG_REACT_ENABLED=true
```

## Handoff

Plan doc: `.ai/INTEGRATION-AGENTS-PLAN.md`. Default flags remain off for safe rollout.
