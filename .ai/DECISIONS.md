# DECISIONS.md

Recorded product/engineering decisions found in repo docs and code. Add new entries when agents make lasting choices.

## D-001 — Gate actions by class × blast radius, not by tool

- **Source:** README Risk Engine section; `app/intelligence/risk_engine.py`
- **Decision:** Classify every recommended action; escalate by blast radius; never gate safety-direction (rollback/isolate).
- **Consequence:** Skills and findings must carry classification metadata (`app/skills/classification.py`).

## D-002 — Only diagnose skills are workflow-safe

- **Source:** README; `WORKFLOW_SAFE` in `app/skills/classification.py`
- **Decision:** Unattended intelligence workflows run read-only diagnose skills only.
- **Consequence:** Generators/executors/architect are chat/delivery driven, not cron-autonomous by default.

## D-003 — Secrets boundary

- **Source:** README Storage; `.env.example` header
- **Decision:** Postgres holds Azure OpenAI + cloud/GitHub connection secrets. Env holds infra URLs, JWT, SMTP, OAuth client secrets, executor key, Langfuse.
- **Consequence:** Do not add LLM keys to `.env` as the primary config path.

## D-004 — Production UI is static export behind FastAPI

- **Source:** README Architecture; `frontend/next.config.ts`; `app/main.py` StaticFiles
- **Decision:** `npm run build` → `frontend/out`; no Next runtime in production.
- **Consequence:** Local HMR uses `next dev` (now `--webpack`); API origin via `NEXT_PUBLIC_API_BASE` / rewrites.

## D-005 — Two RQ planes

- **Source:** `app/intelligence/queue.py`, `app/execution/queue.py`, compose/executor docs
- **Decision:** `intelligence` queue for workflows/architect jobs; org-scoped `org.*.provider.*` for CLI executors.
- **Consequence:** Provider write/read is not consumed by the intelligence worker.

## D-006 — Terraform apply is human Lead-gated and isolated

- **Source:** `docs/solution-architect.md`; delivery/engineering code
- **Decision:** Per-project/per-run workspace; strip host cloud env; apply requires Lead+ and successful plan; architect cannot apply.
- **Consequence:** Generated IaC may PR to GitHub under `infra/infralens/...`; state stays in workspace.

## D-007 — Solution architect is explicit, not auto-routed

- **Source:** README; skill registration notes
- **Decision:** Forced via `/solution_architect` or delivery architecture stage; not workflow-safe.
- **Consequence:** Planner should not silently pick it for arbitrary chat unless forced.

## D-008 — Tenancy isolation is mandatory

- **Source:** `docs/intelligence-layer-2-week-status.md`
- **Decision:** Org → project → users isolation; onboarding when user lacks memberships; project lists must not be global.
- **Consequence:** Any new list/query APIs must scope by org/project membership.

## D-009 — Local Next uses webpack (2026-09-12)

- **Source:** PR #33 / commit `8045b61`; panic logs “Next.js package not found”
- **Decision:** `next dev --webpack` because Turbopack inferred root from home-directory `package-lock.json` and panicked, looping `/login/`.
- **Consequence:** Keep `turbopack.root` pinned to frontend app dir if Turbopack is re-enabled later.
