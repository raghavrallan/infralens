# CURRENT_STATE.md

As of 2026-09-12 on `master` @ `87b9c60` (after merge of PR #33 `fix/stale-architect-runs`).

## Working locally

- Prefer `.\start-local.ps1` for Postgres/Redis + API + RQ worker + `next dev --webpack`.
- Dirty tree observed during inspection (not part of product state): modified `frontend/next-env.d.ts` (Next auto), untracked `_/` — ignore unless intentional.

## Implemented (evidence in repo)

From README, `docs/intelligence-layer-2-week-status.md`, and code:

- Chat + skill registry (20 skills registered in `app/skills/__init__.py`)
- Intelligence workflows, findings, risk engine, RQ worker, scheduler
- Solution architect graph + delivery architecture stage + ADR findings path
- Org tenancy, RBAC, invites/SMTP, onboarding, membership approval
- Delivery checklist (role-aware), engineering memory strip, break-glass surfaces
- Isolated Terraform workspaces, GitHub PR sync for IaC, Lead-gated apply
- Provider executor containers + org executor settings/scale controller
- Quality Gates CI + Deploy workflow
- Local Next login/HMR hardening (webpack + session validation) merged via #33
- Stale/zombie architect & workflow run failure handling merged via #33 lineage
- ADR persistence fixes (finding fingerprint upsert, blast_radius coercion)

## Intentionally incomplete / out of scope (this milestone)

From README roadmap and body:

- Full **actuation** of reversible / human-approval / two-person change execution on the finding→gate path
- Fully populated approvals inbox UX (diff, dry-run, rollback plan) + bounded break-glass path completion
- Engineering memory **feeding back** into Risk Engine as precedent
- Complete redirect-based SSO for Azure / AWS / GitHub
- MCP servers for skill reuse

## Docs dated status (2026-07-30)

`docs/intelligence-layer-2-week-status.md` / plan:

- Tenancy/RBAC/onboarding/delivery checklist marked Done after isolation fix
- ACR / Container App redeploy steps (T17, T28) **skipped by request**
- Referenced Excel/Word plan artifacts may exist under `docs/`; treat plan markdown as the durable checklist

## EQIP scenario evidence

- `docs/eqip-chat-scenario-questions.md` — 2026-08-01 scenario pack (reported 28/28 ok in that doc)
- `docs/eqip-messy-chat-scenarios.md` — 2026-08-02 messy multi-turn (reported 8/8 ok)

## Environment assumptions

- Azure OpenAI must be configured in Settings for chat/architect to work
- Provider inventory needs project connections (Azure/AWS/GitHub)
- SMTP + `PUBLIC_APP_URL` required for invite/approval email links
