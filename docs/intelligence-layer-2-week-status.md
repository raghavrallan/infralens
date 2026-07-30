# InfraLens 2-Week Delivery — Implementation Status

**Date:** 2026-07-30  
**Scope:** Intelligence Layer gaps + **real multi-org tenancy** + RBAC + Onboarding + E2E delivery  
**PDF:** skipped (Excel + Word + this Markdown)  
**Deploy:** skipped per request

## Honest status (post tenancy fix)

Previous checklist marked many items Done while **org→project→users isolation did not exist**. That caused:

- New users seeing admin projects (global `list_projects`)
- Onboarding never showing (`needs_onboarding` used any global mapped repo)

### Now implemented

| Area | Status |
|------|--------|
| Organizations (Super Admin create) | Done |
| Org Admin invite-by-email (SMTP) | Done |
| Org → project → users isolation | Done |
| DevOps Lead member requests → Org Admin approve (portal + email link) | Done |
| Per-user onboarding (empty membership → wizard) | Done |
| RBAC capabilities + project access checks | Done |
| Break-glass UI + approve uses **effective** gate | Done |
| Delivery checklist role-aware Advance | Done |
| Engineering Memory strip on dashboard | Done |
| Accept-invite + Organizations nav section | Done |

### Skipped

- Container App / ACR redeploy (T17, T28 deploy steps)

## Hierarchy

1. **Super Admin** creates organizations and assigns Org Admins.
2. **Org Admin** invites users by email, manages org roles/projects, approves Lead member requests.
3. **DevOps Lead** manages a project day-to-day; adding/removing project members requires Org Admin approval.
4. Orgs are isolated; projects are isolated within orgs.

## CEO demo script

1. Login as Super Admin → **Organizations** → create org (or use InfraLens) → assign Org Admin if needed.
2. Org Admin → Invite user by email → user opens `/accept-invite?token=…` → set password.
3. New user lands in onboarding (no projects) → connect GitHub → create/select repo → finish.
4. Confirm new user **cannot** see other orgs’ projects.
5. Lead proposes project member → Org Admin approves in Organizations → Requests (or email link).
6. Dashboard → Delivery checklist / Break-glass / Approvals / Engineering memory.

## Env knobs

- `SMTP_HOST` / `SMTP_PORT` / `SMTP_USER` / `SMTP_PASS` / `SMTP_FROM`
- `PUBLIC_APP_URL` (invite + approval links)
- `GITHUB_OAUTH_*` / `AZURE_OAUTH_*` (optional)
