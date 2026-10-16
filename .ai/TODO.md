# TODO.md

Prioritized from README roadmap + status docs. Do not invent new product goals.

## Next milestones (README)

1. Wire **actuation** onto finding → risk → gate path (reversible + undo, human approval, two-person; never-gated rollback).
2. Populate **approvals inbox** with informed, time-boxed approvals (diff, blast radius, dry-run, rollback plan) and bounded break-glass.
3. Feed approved/rejected outcomes into **engineering memory** and surface precedent back into the Risk Engine.
4. Complete **redirect-based SSO** login for Azure / AWS / GitHub.
5. **MCP servers** so external models/tools can reuse skills.

## Ops / deploy (from 2-week status — skipped earlier)

- [ ] T17 Week-1 deploy (skipped by request in plan)
- [ ] T28 Final ACR / Container App redeploy (skipped by request)

Confirm with humans before treating these as active work.

## Single-product merge

- [x] Phase 1 — branch `combine-infralens-live`
- [x] Phase 2 code — shared tenancy model and the ported access tests. The full tenancy pytest command still fails on the delivery stage walk (B-003).
- [ ] Phase 3 — session cookie and merged RBAC. `org_owner` is stored; suite `is_org_admin()` does not grant that role yet.
- [ ] Phase 4 — cost fold fixture from `check-access.mjs` (`K-05`) and Azure read plane
- [ ] `test_delivery_walks_remaining_stages` needs Azure OpenAI in `app_config` before that stage walk can pass. Not a Phase 2 schema failure.

## Agent hygiene (ongoing)

- [ ] Keep `.ai/SESSION.md` updated after each meaningful session
- [ ] When fixing bugs, add a short entry to `BUGS.md` (open → resolved)
- [ ] Prefer merging quality-green PRs; Deploy runs only after `master` push

## Unknown / needs verification

- Live production health after PR #33 merge deploy (check Actions for latest Deploy run)
- Whether Excel/Word delivery-plan binaries under `docs/` are still authoritative vs markdown status
