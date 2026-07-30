# InfraLens 2-Week Plan — Living Checklist

Status as of 2026-07-30. **PDF skipped** (Excel + Word + Markdown only).

See also: [`intelligence-layer-2-week-status.md`](./intelligence-layer-2-week-status.md),  
[`InfraLens_2Week_Delivery_Plan_STATUS.xlsx`](./InfraLens_2Week_Delivery_Plan_STATUS.xlsx),  
[`InfraLens_2Week_Delivery_Plan_STATUS.docx`](./InfraLens_2Week_Delivery_Plan_STATUS.docx).

## Gaps → MVP

| Gap | Status |
|-----|--------|
| Action full diff + rollback required | YES |
| Informed approvals + break-glass + Engineering Memory | YES |
| Six module thin actuators | YES |
| RBAC (6 roles) + Users page | YES |
| Onboarding (existing vs new GitHub repo) | YES |
| GitHub/Azure OAuth **or** token/secret | YES |
| Create GitHub repo for new projects | YES |
| E2E delivery (docs→arch→TF→infra→code) | YES |
| Docs pack (MD + Excel; PDF skipped) | YES |

## Task checklist (T01–T28)

- [x] T01–T16 Platform / RBAC / onboarding / memory / break-glass (APIs)
- [ ] T17 Week-1 deploy *(skipped by request)*
- [x] T18–T25 Delivery + modules
- [x] T26 QA checklist tests
- [x] T27 Docs refresh
- [ ] T28 Final ACR deploy *(skipped by request)*

## Tenancy fix (2026-07-30)

Real **org → project → users** isolation + email invites + Lead member-request approvals shipped after the earlier false “Done” status. See [`intelligence-layer-2-week-status.md`](./intelligence-layer-2-week-status.md).

## CEO demo script

1. Login as seed Super Admin.
2. Onboard: PAT → existing or new GitHub repo → optional Azure SP.
3. Dashboard → Delivery checklist → advance stages (Lead for apply).
4. Review informed approval (rationale, blast, rollback, precedent).
5. Settings → Users & roles → create Viewer; confirm writes 403.
6. Lead: open break-glass → one-step gate softens → expire.
