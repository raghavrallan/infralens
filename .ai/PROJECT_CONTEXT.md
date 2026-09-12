# PROJECT_CONTEXT.md

Last updated: 2026-09-12  
Branch inspected: `master` @ `87b9c60`  
Remote: `https://github.com/raghavrallan/infralens.git`

## Identity

- **Product name (UI/API):** InfraLens Skills Suite (`app/main.py`)
- **Repo folder name:** `devsecops-skills-suite`
- **Package version:** `0.1.0` (`app/__init__.py`)
- **Status (README):** first milestone of the Intelligence Layer; Azure OpenAI only (integration isolated for other providers later)

## Problem / value

DevSecOps LLM platform that:

1. Routes chat to specialist **skills**
2. Runs unattended **diagnose** workflows into gated **findings**
3. Supports multi-org **delivery** (architect → Terraform → apply with human gates)

Core design rule: **classify and gate actions, not tools** (`app/intelligence/risk_engine.py`).

## Primary surfaces

| Surface | URL (local) | Notes |
|---------|-------------|-------|
| Chat | API `:8000/` or Next `:3000/` | Agent / Plan modes |
| Dashboard | `/dashboard/` | Intelligence + delivery + memory |
| Wiki | `/wiki/` | Per-skill docs |
| Settings | `/settings/` | Azure OpenAI + cloud connections (Postgres) |
| Organizations | `/organizations/` | Tenancy admin |
| Onboarding / invite | `/onboarding/`, `/accept-invite/` | New-user flows |

## Tech stack (verified)

| Layer | Choice |
|-------|--------|
| API | FastAPI, Python (CI 3.11; local `start-local.ps1` targets 3.12 venv) |
| DB | Postgres + SQLAlchemy (`app/core/db.py`); schema via `init_db`/`_migrate` (not Alembic in-tree) |
| Queue | Redis + RQ — queue `intelligence` + org-scoped `org.*.provider.*` |
| LLM | Azure OpenAI via Settings/`app_config`; Langfuse optional |
| Frontend | Next.js 16.2.10, React 19.2.7, TypeScript, Tailwind 4 |
| Executors | Docker images under `executors/` (az / aws / gh CLIs) |
| IaC | Terraform in isolated `.terraform-workspaces/{project_id}/{run_id}` |

## Dependencies & env

- Python: `requirements.txt` + `requirements-dev.txt`
- Frontend: `frontend/package.json` / lockfile
- Infra config only in `.env` — see `.env.example`. **Do not store Azure OpenAI or cloud secrets in env** (Settings → Postgres).
- Tests: `.env.test`; `RUN_INFRA_TESTS` controls Postgres/Redis cases and 90% coverage gate.

## Development commands

```powershell
# Preferred Windows local stack
.\start-local.ps1 setup
.\start-local.ps1 start          # optional: -WithExecutors
.\start-local.ps1 stop
.\start-local.ps1 seed           # shared tenant seed script

# Quality (same spirit as CI)
.\scripts\quality.ps1
# or: make quality

pytest tests/unit
pytest tests/integration   # needs RUN_INFRA_TESTS=true + test DB
pylint app executors
```

```bash
docker compose up -d postgres redis
docker compose --profile container-app up --build   # full containerized stack
docker compose -f docker-compose.local-executors.yml up --build
```

## Conventions

- New skill: `app/skills/<name>.py` exporting `skill = ...`, then register in `app/skills/__init__.py`.
- RBAC hierarchy: `super_admin > org_admin > devops_lead > devops_engineer > developer > viewer` (`app/core/rbac.py`).
- Frontend auth: JWT in `localStorage` (`infralens_auth_token`); `AuthGate` protects app shells.
- Production UI is static export served by FastAPI; local HMR uses `next dev --webpack`.

## Related human docs

- `README.md` — product + quick start + quality gates + roadmap
- `docs/solution-architect.md` — architect pipeline + IaC isolation
- `docs/intelligence-layer-2-week-status.md` / `*-plan.md` — tenancy/delivery status (dated 2026-07-30)
- `docs/eqip-*-scenarios.md` — EQIP chat scenario results
- `deploy/server/README.md`, `deploy/azure/README.md`
