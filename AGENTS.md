# AGENTS.md

Infralens is the multi-client Azure console. It is not the AthletesGoLive mock in `agl-infralens`.

Read `.ai/CURRENT_STATE.md` before changing behavior.

- Do not put mock cost, resources, or invoices back into the product path.
- Do not call Azure for a subscription that is not attached to the selected project.
- Do not return client secrets, access tokens, secret values, or another organization's rows. Do not grant Azure RBAC from this repo.
- Console Azure reads go through the sandbox in `src/lib/azure/sandbox.js` and `src/lib/azure/cli.js`. That is `az`, including `az rest`. `src/lib/azure/arm.js` throws if imported. Do not add a Node `fetch` to Azure.
- On-demand reads are cached in Redis for one hour by `src/lib/read-cache.js`. A read of one resource must include that resource's name and group in the cache key. Do not serve one resource's payload for another.
- Chat Azure reads in `engine/app/providers/azure_infra.py` still use HTTP. Do not describe those as sandbox calls.
- The skills engine is `engine/app`, imported as `app` with `PYTHONPATH=engine`. Do not put a Python package at the repo-root `app/` directory. Next.js will prefer it over `src/app` and every page 404s.
- Agentic pages stay in the live shell. Do not add a second frontend, and do not describe them as a separate suite. The browser calls `/suite-api/*`, which proxies to the FastAPI process. Local Linux start is `scripts/start-suite.sh`. The console is port 3001. The API uses `APP_PORT` (8001 when 8000 is taken).
- Postgres is the system of record for the console and the agentic engine. Do not add SQLite back.
- `data/` is local secret storage, including Azure CLI profiles. Do not commit it or a real `.env`.
- Do not start a full estate cost sync to fix a page. Cost Management returns 429, and a failed sync must not replace a ready snapshot.
- Run `npm run check` after changing access or cost folding.

<!-- BEGIN:nextjs-agent-rules -->

# This is NOT the Next.js you know

This version has breaking changes — APIs, conventions, and file structure may all differ from your training data. Read the relevant guide in `node_modules/next/dist/docs/` (resolved from this file's directory; in monorepos the `next` package may not be visible from the repo root) before writing any code. Heed deprecation notices.

This block is written and re-added by `next dev` — verify at `node_modules/next/dist/server/lib/generate-agent-files.js`. Removing it from a diff only re-creates the uncommitted change; committing it with your work keeps the tree clean.

<!-- END:nextjs-agent-rules -->
