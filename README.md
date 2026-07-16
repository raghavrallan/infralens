# DevSecOps LLM Skills Suite

A chatbot-driven **library of DevSecOps skills** powered by LLMs (Azure OpenAI).
Each skill is a reusable, self-contained capability mapped to the managed
service operating model — mobilise, baseline, transform, operate, improve.

> Status: **first draft** for internal review. Azure OpenAI only for now; the
> integration point is isolated so other providers can be added later.

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
- `app/skills/*.py` — one file per skill (metadata, wiki, system prompt, schema).
- `app/orchestrator.py` — modes, forced-skill routing, and the multi-agent
  planner/executor.
- `app/db.py` — SQLAlchemy engine, models (`app_config`, `connections`), init.
- `app/config.py` — Postgres-backed Azure OpenAI configuration.
- `app/connections.py` — Postgres-backed Azure/AWS/GitHub credential store.
- `app/azure_client.py` — the single Azure OpenAI integration point.
- `app/main.py` — FastAPI app (chat, skills, skill detail, config, connections).
- `app/static/` — chat, wiki and settings pages.

## Storage

All configuration and credentials live in **Postgres** (run via Docker), not in
environment files:

- `app_config` — Azure OpenAI endpoint, key, deployment, API version.
- `connections` — Azure / AWS / GitHub connection method + fields.

Only the Postgres connection string (`DATABASE_URL`) comes from the environment.

## Quick start

```bash
# 1. Start Postgres (Docker)
docker compose up -d

# 2. Create a virtual environment
python -m venv .venv
# Windows PowerShell:
.venv\Scripts\Activate.ps1
# macOS/Linux:
# source .venv/bin/activate

# 3. Install dependencies
pip install -r requirements.txt

# 4. (Optional) point at a non-default database
copy .env.example .env      # Windows  (cp on macOS/Linux)
# the default DATABASE_URL already matches docker-compose.yml

# 5. Run
uvicorn app.main:app --reload
```

Open http://127.0.0.1:8000, then go to **Settings** and add your Azure OpenAI
endpoint, key and deployment — these are saved to Postgres. The wiki and
Settings pages work before Azure is configured.

## Adding a new skill

1. Create `app/skills/my_skill.py` with a class extending `Skill` and expose a
   module-level `skill = MySkill()`.
2. Import and register it in `app/skills/__init__.py`.

That's it — it automatically appears in the catalog and becomes callable by the
chatbot.

## Roadmap (post-draft)

- Wire stored connections into tool-using skills (call real GitHub / K8s /
  cloud / scanner APIs, not just reason over pasted input)
- Complete redirect-based SSO login flows for Azure / AWS / GitHub
- RAG over runbooks and past post-mortems
- MCP servers so any model/tool can reuse the skills
- Streaming responses and multi-provider support
