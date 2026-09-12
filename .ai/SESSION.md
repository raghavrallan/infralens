# SESSION.md

Last session: 2026-09-12  
Branch: `feature/dashboard-declutter`

## Purpose

Implement dashboard declutter: overview + Delivery on hub; move major surfaces to subroutes with sidebar sub-nav. Tighten Findings / Approvals / Workflows / Architecture page structure.

## Done

- `DashboardShell` + `lib/dashboard.ts` shared chrome/context
- Overview hub with clickable metric tiles + DeliveryChecklist + MemoryStrip
- Subroutes: findings, approvals, workflows, architecture, engineering, break-glass
- FastAPI routes for nested dashboard HTML
- Shared `.dash-page` / `.dash-feed` layout; compact expandable cards
- Findings + Approvals: show 25 at a time with Load more; evidence only when expanded
- Workflows: Definitions | Recent runs two-column layout
- Architecture: compact run list, expand for diagram/decisions
- Verified locally via Playwright CLI login as `raghavrallan`
- `npm run typecheck` green

## Handoff

Open `/dashboard/` then use left sub-nav. Playwright MCP was not available in session; used `_screenshots/capture.mjs` instead (gitignored).
