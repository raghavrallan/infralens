# Changelog

## 2026-10-31

- Console Azure reads go through the isolated Azure CLI sandbox again. `az rest` is the CLI. `src/lib/azure/arm.js` throws if something imports it. Every sandbox spawn is audited, without passwords or request bodies.
- Compute, data, network, and platform have hubs and per-service pages: status, inventory, a detail tab, activity, metrics, KQL, availability, and alerts.
- SQL servers, databases, and elastic pools are separate. Storage shows container names, account used size, and last update. Network detail lists subnets, listeners, rules, and Front Door endpoints. Platform catalogs list key, secret, and certificate names, APIs, queues, hubs, runs, and model deployments. Secret values stay in Azure.
- On-demand reads are cached in Redis for one hour. The key for a single resource includes its name and resource group, so one resource cannot reuse another's copy. The schedule refreshes stored reads after a successful snapshot. Log tails are not hour-cached.
- The activity log is read per resource provider and capped per type. Container Apps and SQL no longer fill the only saved slice.
- The console and the skills engine share Postgres. Local start on Linux is `scripts/start-suite.sh`.

## 2026-10-20

- Repeat estate views return the in-memory snapshot. A snapshot younger than 60 seconds is final. A snapshot younger than 15 minutes is shown immediately and refreshed in the background.
- Skills-engine Azure token requests are cached in the API process until near expiry.
- Docs updated for the merged layout: `engine/app`, `/suite-api`, and the Next.js shell as the only UI.

## 2026-10-17

- Copied the GitHub skills engine into this repo: FastAPI `engine/app`, executors, tests, deploy, compose, and quality workflows. Did not copy that repo's frontend.
- Added suite screens in the live shell: chat, wiki, findings, workflows, approvals, architecture, engineering, break-glass, suite settings, invite accept, and membership approval. They call the engine through `/suite-api`.
- Moved the Python package from repo-root `app/` to `engine/app` so Next.js keeps serving `src/app`.

## 2026-10-04

- Started the live draft from the Infralens console. Removed the mock estate. Added organizations, projects, encrypted app-registration connections, and Azure reads scoped to project subscriptions.
- A client ID can be stored once. Saving it again updates that connection. The secret stays encrypted and is not returned to the browser. One connection can be mapped to many projects, but not twice on the same project.
- Slow actions show a blocking loader. Failures show a red toast on sign-in, organization settings, and Azure reads.
