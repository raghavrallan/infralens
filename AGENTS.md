# AGENTS.md — InfraLens / DevSecOps Skills Suite

Persistent onboarding for AI agents. **Read this first**, then `.ai/` for deeper memory.
Do not rely on prior chat history. Treat the repository + `.ai/` as source of truth.

## What this product is

**InfraLens Skills Suite** (GitHub: `raghavrallan/infralens`) — a DevSecOps product with:

1. **Chat / Skills** — LLM-routed reusable skills (Azure OpenAI today).
2. **DevOps Intelligence Layer** — queued diagnose workflows → findings gated by **action class × blast radius**.
3. **Engineering / delivery** — org tenancy, onboarding, delivery checklist, solution architect graph, isolated Terraform workspaces, provider CLI executors.

Differentiation (from README): gate by action class × blast radius, not by tool name.

## Canonical paths

| Path | Role |
|------|------|
| `app/main.py` | FastAPI entry: auth middleware, API routes, SPA static mount |
| `app/api/` | `routes_mvp.py`, `routes_engineering.py` |
| `app/skills/` | Skill modules + registry (`__init__.py`) |
| `app/chat/` | Orchestrator, chats, memory, project context |
| `app/intelligence/` | Workflows, RQ worker/queue, risk engine, findings, scheduler |
| `app/agents/solution_architect/` | Clarify→…→finalize architecture pipeline |
| `app/platform/` | Connections, delivery, break-glass, engineering IaC/tasks |
| `app/execution/` | Provider action jobs, Terraform runner, approvals |
| `app/tenancy/` | Orgs, projects, memberships, invites, onboarding |
| `app/org_executors/` | Per-org executor pool scaling |
| `app/core/` | DB models, JWT/RBAC, Azure OpenAI config, observability |
| `executors/` | Dockerized Azure/AWS/GitHub CLI RQ workers |
| `frontend/` | Next.js 16 app (static export in prod; `next dev --webpack` locally) |
| `docs/` | Architect + intelligence status/plan + EQIP scenario notes |
| `.ai/` | Project memory for agents (update when you learn something lasting) |

## Runtime model

- **Production:** FastAPI serves API + `frontend/out` (Next `output: "export"`). No Next server.
- **Local (recommended):** `.\start-local.ps1 setup` then `.\start-local.ps1 start`
  - Docker: Postgres `:5544`, Redis `:6399`
  - API `:8000`, Next live UI `:3000`, RQ `intelligence` worker
  - Optional: `-WithExecutors` or `docker-compose.local-executors.yml`
- LLM + cloud credentials: **Postgres via Settings UI**, not `.env`.
- Env holds: `DATABASE_URL`, `REDIS_URL`, JWT/SMTP/OAuth/Langfuse/executor keys (see `.env.example`).

## Agent workflow (required)

1. Read `AGENTS.md` → `.ai/PROJECT_CONTEXT.md` → `.ai/SESSION.md` → relevant other `.ai/*`.
2. Prefer existing docs (`README.md`, `docs/solution-architect.md`) over guessing.
3. After meaningful work, **update** `.ai/SESSION.md`, and as needed `CURRENT_STATE.md`, `TODO.md`, `BUGS.md`, `DECISIONS.md`, `CHANGELOG.md`.
4. Do not invent product facts. If unknown, write **unknown** and cite what you checked.
5. Do not commit secrets (`.env`), untracked junk (`_/`), or auto-generated `frontend/next-env.d.ts` noise unless intentionally required.

## Quality bar

- PRs: `.github/workflows/quality.yml` — Pylint ≥ 9.0, unit + integration; 90% coverage only when `RUN_INFRA_TESTS=true`.
- Merge to `master` triggers `.github/workflows/deploy.yml` (rsync + SSH); does **not** re-run quality.
- Local: `.\scripts\quality.ps1` or `make quality`.

## Safety rules (product)

- Only workflow-safe **diagnose** skills run unattended (`app/skills/classification.py`).
- Terraform **apply** is Lead-gated; architect graph is read-only for infra apply.
- Never gate safety-direction actions (rollback/isolate) — see Risk Engine.

## Deeper memory

See `.ai/ARCHITECTURE.md`, `.ai/CURRENT_STATE.md`, `.ai/DECISIONS.md`, `.ai/TODO.md`, `.ai/BUGS.md`, `.ai/CHANGELOG.md`, `.ai/SESSION.md`.
