# Current state

Remote: `https://github.com/raghavrallan/infralens.git`. This tree is the Next.js console and the engine at `engine/app`. It replaces the previous root `app/` and `frontend/` layout.

The console and the agentic engine use one Postgres database. Organization sign-in is the `il_session` cookie. Agentic screens still use their own JWT. They are pages in this shell, not a separate suite.

Estate pages read a saved snapshot. Compute, data, network, and platform each have a hub and a page per service: overview, inventory, a service-specific detail tab, activity, live metrics, availability, and alerts. Detail tabs (subnets, listeners, SQL allow lists, blob containers, key and API catalogs, container revisions) load through the sandbox and stay in Redis for an hour, one copy per resource.

The Sandbox page shows the CLI stream, the call audit, and how much memory the read cache uses. A person can delete one cached read or the whole project cache.

`scripts/start-suite.sh start` brings up Postgres, Redis, the API, the RQ worker, the estate Celery worker, and the console. The console listens on port 3001.

Chat can run a skill or return a plan for the selected project. Workflows, findings, architecture, engineering, and break-glass are the rest of that agentic side. A workflow run waits for the RQ worker. Approval records a decision and does not execute the change from the inbox.

Chat skills still read Azure over HTTP inside the engine. Those reads are outside the sandbox log.
