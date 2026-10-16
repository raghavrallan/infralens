# SESSION.md

Last session: 2026-10-16  
Branch: `combine-infralens-live` (from `master` @ `5949865`)

## Purpose

Phase 1 and Phase 2 of the single-product merge. `infralens-live` stays the reference at `9e49342`.

## Done this session

- Branch `combine-infralens-live`. No page or Azure calls.
- Postgres models for org-level `azure_connections`, `subscriptions`, `project_connections`, `project_subscriptions`, `sessions`, and `audit_log`.
- Projects gained `slug` (unique per org) and nullable `budget_usd`.
- Live access checks, AES-256-GCM secret box, and scrypt password verification ported. Suite pbkdf2 hashes still verify.
- `tests/integration/tenancy/test_live_access.py` ports `scripts/check-access.mjs` except the cost-fold fixture (`K-05`, Phase 4).

## Verification

- `pytest tests/test_tenancy.py tests/integration/tenancy -q` — one failure: `test_delivery_walks_remaining_stages`. Architecture generation stops with “Azure OpenAI is not configured.” That path was not edited. The new access tests passed.
- Pylint on the touched modules: 9.84.
- `infralens-live` HEAD `9e49342`, worktree clean. Skill registry still 21 names. Azure CLI `ALLOWED` still 15 tokens.

## Not in this phase

- Browser cookie, merged RBAC ladder, and signup HTTP route (Phase 3).
- Cost row folding (Phase 4).
- Estate pages.

## Handoff

Phase 3 owns session cookie plus suite/live role mapping. `org_owner` is stored, and `can()` treats an owner as an org manager. `is_org_admin()` still matches only `org_admin` until that mapping lands. Do not start Phase 3 from a dirty tree.

Previous session note (2026-09-12): agent-runtime flags stay default-off. See `.ai/CHANGELOG.md`.

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
