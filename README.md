# DevSecOps LLM Skills Suite

A **DevSecOps product** powered by LLMs (Azure OpenAI) with two execution modules
on one platform:

1. **Chat / Skills** — a chatbot-driven library of reusable DevSecOps skills, each
   mapped to the managed service operating model (mobilise, baseline, transform,
   operate, improve).
2. **DevOps Intelligence Layer** — a dashboard fed by skills that run
   **autonomously in a queue**, where every recommended action is gated by
   **action class × blast radius**, not by tool.

> Status: **first milestone** of the Intelligence Layer. Azure OpenAI only for
> now; the integration point is isolated so other providers can be added later.

## DevOps Intelligence Layer

The design principle is to **classify actions, not tools**. Gating "Terraform"
is wrong; gating "an irreversible, high-blast change to production" is right. The
Risk Engine resolves a gate for every action from its class and blast radius:

| Action class | Dev / Staging | Production |
|---|---|---|
| Read / diagnose | Autonomous | Autonomous |
| Reversible change | Autonomous, logged | Auto + instant-undo + notify |
| Config / code change | Auto-apply | Human approval |
| Irreversible / high-blast | Human approval | Two-person rule |
| Safety-direction (rollback, isolate) | Autonomous | Autonomous — never gate the exit |

A high blast radius escalates a change gate by one step, and safety-direction
actions are never gated: you gate entry into risk, never the escape from it.

**What runs unattended.** Only read-only *diagnose* skills are marked
workflow-safe (`app/skills/classification.py`) and can be scheduled or run on
demand. They are grouped under the six agent modules — Pipeline Intelligence,
Release Confidence, Infrastructure as Code, Incident Response, Security & Patch,
and FinOps. A workflow runs its skills in a Redis/RQ worker, normalizes each
skill's output into discrete **findings**, and attaches the Risk Engine gate to
every finding before it reaches the dashboard.

**Design rules realized now.** Every finding carries a recommended action plus
its gate (diff-first); the approvals path is scaffolded with a time-boxed
`expires_at` and a break-glass-ready model; and an engineering-memory table is in
place to later turn approved/rejected outcomes into retrievable precedent.
Change execution and approval actuation are intentionally out of scope this
milestone.

### How this differs from the market

Coforge **Forge-X / EvolveOps.AI**, Zensar **ZenseAI.AgentMesh**, and Globant
**Glob.AI OS / AI Pods** all sell agent marketplaces with governance layered on
top. This product's differentiator is the **safety model itself**: gating by
action class × blast radius, a diff- and rollback-first execution path, and
engineering memory as precedent — rather than a generic catalog of agents.

## Interaction model

- **Two modes.** *Agent* mode executes work; *Plan* mode is read-only and only
  returns the ordered set of skills it would run, with rationale.
- **Multi-agent tasks.** In Agent mode with "Auto" selected, a planner
  decomposes the request into steps, runs each step as a separate skill agent,
  and synthesises the results into one answer.
- **Pick a skill three ways.** Let the agent choose (Auto), select one from the
  dropdown, or type `/` in the composer to choose a skill inline.
- **Wiki.** Every skill has its own documentation page describing what it does,
  when to use it, what to feed it, and what you get back.
- **Settings.** Configure Azure OpenAI and connect Azure, AWS and GitHub
  accounts (via client secret / key / token, or record an SSO directory).
  Everything is stored in Postgres and secrets are never returned to the
  browser.

## What's inside

A single chat entry point routes each request to the right specialist skill.
The current skill library:

| Skill | Control area | What it does |
|---|---|---|
| **Pipeline Auditor** | Source, quality & dependency security | Audits CI/CD configs against DevSecOps best practices |
| **Pipeline Generator** | Delivery & supply-chain controls | Generates secure CI/CD pipelines (SAST, SCA, SBOM, signing, gates) |
| **IaC Reviewer** | Infrastructure & cloud security | Reviews Terraform/K8s/Helm for misconfigurations |
| **Policy Generator** | Infrastructure & cloud security | Turns plain-English guardrails into OPA/Kyverno policy-as-code |
| **Vuln Triage** | Observability & response | Deduplicates + prioritises scanner findings (JSON output) |
| **Compliance Mapper** | Risk & compliance visibility | Maps controls to SOC2 / ISO 27001 / PCI-DSS and finds gaps |
| **Incident Analyzer** | Observability & response | Proposes root cause, remediation, and a draft post-mortem |
| **Report Writer** | Executive transparency | Turns raw KPIs into an executive-ready service report |

## Architecture

```
Browser chat UI  ──▶  FastAPI (/api/chat)  ──▶  Orchestrator
                                                   │  (LLM tool-calling picks a skill)
                                                   ▼
                                             Skill Registry
                                         ┌───────┴────────┐
                                     Skill A            Skill B ...
                                   (own system         (own system
                                    prompt + schema)    prompt + schema)
                                         └──── Azure OpenAI ────┘
```

- `app/skills/base.py` — `Skill` base class (incl. wiki docs) + `SkillRegistry`.
- `app/skills/classification.py` — action class, blast radius and the
  workflow-safe set for every skill.
- `app/skills/*.py` — one file per skill (metadata, wiki, system prompt, schema).
- `app/chat/orchestrator.py` — modes, forced-skill routing, and the multi-agent
  planner/executor.
- `app/intelligence/risk_engine.py` — the action-class × blast-radius gate matrix.
- `app/intelligence/workflows.py` — workflow / run / finding persistence + the
  six-module mapping.
- `app/intelligence/queue.py` — Redis/RQ wiring.
- `app/intelligence/worker.py` — the `run_workflow` job executed by `rq worker`.
- `app/intelligence/findings.py` — normalizes skill output into gated findings.
- `app/intelligence/scheduler.py` — APScheduler cron enqueue.
- `app/core/db.py` — SQLAlchemy engine, models, init (chat + intelligence tables).
- `app/core/config.py` — Postgres-backed Azure OpenAI configuration.
- `app/platform/connections.py` — Postgres-backed Azure/AWS/GitHub credential store.
- `app/core/azure_client.py` — Azure OpenAI for one-shot skills (Langfuse OpenAI drop-in).
- `app/agents/solution_architect/` — agentic architect graph (clarify → explore →
  design → critique → senior verify → finalize). Forced via `/solution_architect`
  in Chat Agent or Plan; also powers the delivery `architecture` stage. Not
  auto-routed and not workflow-safe. ADRs land in the existing Findings /
  Approvals inbox, classified per decision.
- `app/main.py` — FastAPI app (chat, skills, workflows, runs, findings, config).
- `frontend/` — Next.js TypeScript app exported as static files for FastAPI.

The browser frontend is built by Next.js but served by the same FastAPI/Uvicorn
process as the API. There is no Next.js runtime server in production: `npm run
build` creates `frontend/out`, and Uvicorn serves that export alongside `/api`.

## Storage

All configuration and credentials live in **Postgres** (run via Docker), not in
environment files:

- `app_config` — Azure OpenAI endpoint, key, deployment, API version.
- `connections` — Azure / AWS / GitHub connection method + fields.

Only the Postgres connection string (`DATABASE_URL`) comes from the environment.

## Quick start

```bash
# 1. Start only Postgres + Redis (Docker)
docker compose up -d postgres redis

# 2. Create a virtual environment
python -m venv .venv
# Windows PowerShell:
.venv\Scripts\Activate.ps1
# macOS/Linux:
# source .venv/bin/activate

# 3. Install dependencies
pip install -r requirements.txt

# 4. Build the Next.js frontend (Node 22+)
cd frontend
npm install
npm run build
cd ..

# 5. (Optional) point at a non-default database / redis
copy .env.example .env      # Windows  (cp on macOS/Linux)
# the default DATABASE_URL already matches docker-compose.yml
# REDIS_URL defaults to redis://localhost:6399/0 (the compose mapping)

# 6. Run the single local frontend + API entrypoint
uvicorn app.main:app --reload

# 7. In a second shell, run the worker that executes queued workflows.
# This cross-platform worker class runs in-process with a timer-based timeout,
# so it works on Windows (no SIGALRM) as well as Linux/Docker.
rq worker intelligence --worker-class app.intelligence.worker.Worker --url redis://localhost:6399/0
```

Open http://127.0.0.1:8000 for the chat and http://127.0.0.1:8000/dashboard for
the Intelligence Layer, then go to **Settings** and add your Azure OpenAI
endpoint, key and deployment — these are saved to Postgres. The wiki and
Settings pages work before Azure is configured.

The default Compose startup intentionally runs only Postgres and Redis. The API,
frontend export, and intelligence worker run locally using the commands above.
Provider write/read actions require an RQ provider executor; they are not
consumed by the intelligence worker. To start the complete containerized stack
with the API, intelligence worker, and all provider executors together, use:

```powershell
docker compose --profile container-app up --build
```

The provider executor containers start their `az`, `aws`, or `gh` CLI check and
RQ worker automatically. No manual provider worker command is needed when the
containerized stack is running.

When Uvicorn is running on the host and only Postgres/Redis are containerized,
start the isolated provider executors with one command:

```powershell
docker compose -f docker-compose.local-executors.yml up --build
```

Those workers connect to the host API at `127.0.0.1:8000` through Docker
Desktop's `host.docker.internal` address and consume approved actions from the
same Redis instance.

If Docker Desktop's corporate proxy certificate is not trusted inside Linux
build containers, use this workstation-only build setting:

```powershell
$env:PIP_TRUSTED_HOSTS = "pypi.org files.pythonhosted.org"
docker compose -f docker-compose.local-executors.yml up --build -d
```

Leave `PIP_TRUSTED_HOSTS` unset in production; normal certificate validation
is the default.

## Adding a new skill

1. Create `app/skills/my_skill.py` with a class extending `Skill` and expose a
   module-level `skill = MySkill()`.
2. Import and register it in `app/skills/__init__.py`.

That's it — it automatically appears in the catalog and becomes callable by the
chatbot.

## Roadmap (next milestones)

- Wire actuation onto the finding → risk → gate path: reversible changes with
  instant-undo, human-approval and two-person flows, and never-gated rollback.
- Populate the approvals inbox with time-boxed, informed approvals (diff, blast
  radius, dry-run, rollback plan) and a bounded break-glass path.
- Feed approved/rejected outcomes into engineering memory and surface precedent
  ("the last three times we approved this class of change, two caused incidents")
  back into the Risk Engine.
- Complete redirect-based SSO login flows for Azure / AWS / GitHub.
- MCP servers so any model/tool can reuse the skills.
