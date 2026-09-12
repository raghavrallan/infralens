# BUGS.md

Track known defects. Prefer evidence (logs, commits, Actions URLs).

## Open

### B-001 — Home-directory lockfile can break Turbopack if webpack flag is dropped

- **Symptom:** FATAL Turbopack panic `Next.js package not found`; repeated `GET /login/`.
- **Cause:** Parent `C:\Users\…\package-lock.json` (e.g. chrome-devtools-mcp) becomes inferred root.
- **Mitigation in tree:** `next dev --webpack` + `turbopack.root` = frontend app dir (`8045b61`).
- **Risk:** Re-enabling default Turbopack without fixing parent lockfiles may regress.

### B-002 — Windows `rq.exe` launcher breaks if venv path moves

- **Symptom:** Worker CMD fails after repo move (e.g. into OneDrive).
- **Mitigation:** `start-local.ps1` uses `python -m rq.cli` (`c5da819`).
- **Status:** Mitigated in scripts; still avoid relying on console entrypoints on Windows.

## Recently fixed (keep for regression awareness)

| ID | Issue | Fix evidence |
|----|-------|--------------|
| F-001 | Deploy Next build: `Cannot find name 'ChecklistItem'` | `c5da819` — type added in `delivery-checklist.tsx` |
| F-002 | Login reload loop + Turbopack panic | `8045b61` — webpack + validate session before redirect |
| F-003 | Zombie architect/workflow runs hang forever | `3b97b3e` and follow-ups on `fix/stale-architect-runs` |
| F-004 | Architect ADRs fail to persist (blast_radius / fingerprints) | `d6e6512`, `be43f0a` |
| F-005 | Chat/architect hang; Terraform apply/repair/revert isolation | `d8f9920` |
| F-006 | Unit tests hitting Postgres tables CI never creates | `00b0976` |

## Notes

- Historical tenancy bug (global project lists / onboarding never showing) documented as fixed in `docs/intelligence-layer-2-week-status.md` — do not reintroduce global `list_projects` behavior.
