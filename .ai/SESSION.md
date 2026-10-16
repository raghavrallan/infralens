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

- `pytest tests/test_tenancy.py tests/integration/tenancy -q` passes (34 tests).
- The unpatched delivery walk fails on `master` @ `5949865` with no Azure OpenAI rows: architecture status `failed`, then Terraform raises `Architecture must be ready before moving to Terraform`. Delivery code was not changed. The tenancy test now asserts that gate and then finishes the walk.
- Pylint on the touched modules: 9.84.
- `infralens-live` HEAD `9e49342`, worktree clean. Skill registry still 21 names. Azure CLI `ALLOWED` still 15 tokens.

## Not in this phase

- Browser cookie, merged RBAC ladder, and signup HTTP route (Phase 3).
- Cost row folding (Phase 4).
- Estate pages.

## Handoff

Phase 3 owns session cookie plus suite/live role mapping. `org_owner` is stored, and `can()` treats an owner as an org manager. `is_org_admin()` still matches only `org_admin` until that mapping lands. Do not start Phase 3 from a dirty tree.

Previous session note (2026-09-12): agent-runtime flags stay default-off. See `.ai/CHANGELOG.md`.
