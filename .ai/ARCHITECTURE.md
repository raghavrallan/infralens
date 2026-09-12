# ARCHITECTURE.md

Derived from code + README + `docs/solution-architect.md`. Last reviewed: 2026-09-12.

## High-level

```text
Browser (Next static or next dev)
    │  JWT Bearer
    ▼
FastAPI (app/main.py)
    ├── Chat / Skills ──▶ Orchestrator ──▶ Skill Registry ──▶ Azure OpenAI
    ├── Intelligence ──▶ RQ queue "intelligence" ──▶ worker ──▶ findings + risk gates
    ├── Solution Architect ──▶ RQ job generate_architecture (in-process fallback)
    ├── Delivery / Engineering APIs ──▶ artifacts, tasks, isolated Terraform
    ├── Tenancy / Auth / RBAC
    └── Internal execution claim APIs ──▶ org provider executor workers
```

Production: one Uvicorn process serves `/api/*` and mounts `frontend/out`.

## Backend packages

| Package | Responsibility |
|---------|----------------|
| `app/api` | MVP + engineering route modules included from `main` |
| `app/chat` | Agent/Plan modes, multi-skill planning, SSE stream, chat memory |
| `app/skills` | ~20 registered skills; `classification.py` marks workflow-safe diagnose set |
| `app/intelligence` | Six modules, runs, findings, risk engine, APScheduler, RQ worker |
| `app/agents/solution_architect` | Sequential graph (default) or LangGraph when `ARCHITECT_LANGGRAPH=true`: clarify → explore → design → critique → verify → finalize |
| `app/agents/runtime` | Shared LLM factory, loop policies, feature flags, LC tools/retrievers |
| `app/agents/debug_graph` | Bounded ReAct facade over execution debug_loop (`DEBUG_REACT_ENABLED`) |
| `app/integrations` | Signed outbound webhooks + n8n event schemas (`N8N_WEBHOOKS_ENABLED`) |
| `app/platform` | Connections, delivery stages, break-glass, engineering IaC/tasks/memory |
| `app/execution` | Structured provider actions, Terraform runner, org RQ queues |
| `app/providers` | Azure/AWS/GitHub inventory adapters |
| `app/tenancy` | Orgs, projects, memberships, invites, onboarding |
| `app/org_executors` | Scale controller for per-org CLI executor pools |
| `app/core` | DB models, JWT, RBAC, Azure OpenAI config, mailer, Langfuse |
| `executors/` | Process workers that pull org provider queues via control-plane HTTP |

## Frontend

- App Router under `frontend/app/` — chat, login, dashboard, settings, wiki, orgs, onboarding, invite, approve-member.
- Shared UI in `frontend/components/` (`chat-page`, `delivery-checklist`, `auth-gate`, `shell`, …).
- `frontend/lib/api.ts` — `NEXT_PUBLIC_API_BASE` in local next-dev; relative `/api` when served by FastAPI.
- `frontend/next.config.ts` — `trailingSlash: true`; export only when not development; rewrites only in development; `turbopack.root` pinned to frontend app dir.

## Data model (tables in `app/core/db.py`)

Tenancy: `organizations`, `org_memberships`, `projects`, `project_memberships`, `users`, `invites`, `membership_requests`, `org_executor_settings`.

Chat/config: `app_config`, `connections`, `chats`, `messages`, `chat_memories`.

Intelligence: `workflows`, `workflow_runs`, `findings`, `finding_identities`, `approvals`, `engineering_memory`.

Delivery/arch: `architecture_runs`, `architecture_decisions`, `delivery_runs`, `delivery_tasks`, `project_requirements`, `project_artifacts`, `project_risks`, `project_activities`, `revert_requests`, `break_glass_sessions`.

Execution: `execution_jobs`, `execution_events`, `execution_approvals`.

Defaults: `DEFAULT_PROJECT_ID = "default"`; seeded org id `00000000-0000-4000-8000-000000000001` (slug `infralens`).

## Key workflows

### Chat

`POST /api/chat` / stream variants → `orchestrator`: Auto skill pick, forced skill, or multi-agent plan. `/solution_architect` forces architect skill (not auto-routed, not workflow-safe).

### Intelligence

Diagnose skills only in `WORKFLOW_SAFE` → RQ → normalize findings → attach Risk Engine gate → dashboard. Approvals model exists with TTL for human/two-person gates; **change actuation still roadmap**.

### Solution architect → delivery

Delivery stages (`app/platform/delivery.py`): ingest → architecture → terraform → plan → apply → code → done.  
Architect job writes progress; Lead+ accepts architecture; task generate writes Terraform into isolated workspace; apply is Lead-gated and not agent-driven (`docs/solution-architect.md`).

### Provider executors

Queues `org.{org_id}.provider.{azure|aws|github}.{read|write}`. Workers authenticate with `EXECUTOR_SERVICE_KEY`. Org scale: local Docker stub or Azure Container Apps (`deploy/azure/README.md`).

## CI/CD

- **Quality Gates** on PR: Pylint ≥ 9.0; unit; integration (+ optional 90% cov if `RUN_INFRA_TESTS=true`). Python 3.11.
- **Deploy** on push to `master`: rsync (excludes `.env`, `node_modules`, `.venv`, …) + SSH `deploy` (`deploy/server/README.md`).

## Risk matrix (product)

Documented in README: action class × environment (dev/staging vs production), with blast-radius escalation and never-gated safety-direction actions.
