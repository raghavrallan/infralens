# Project context

Infralens is one product: a multi-client Azure console and an agentic side in the same shell. There is no separate suite.

Organizations connect their own app registration. Projects inside an organization receive a private set of subscriptions. The console signs that identity into an isolated Azure CLI profile and reads inventory, cost, metrics, and resource detail with `az rest`. Snapshots are stored in Postgres. Repeat detail reads come from Redis for about an hour.

The agentic engine is the Python package at `engine/app`. Chat, wiki, findings, workflows, approvals, architecture, engineering, and break-glass are pages in the Next.js shell. They call FastAPI through `/suite-api`. That path is the proxy. Chat runs a skill in Agent mode or returns steps in Plan mode. The default scope is read-only: analyse and recommend, and label a proposed change as proposed. Workflows enqueue a run when Azure or AWS is connected and the worker is running. Findings stay open with the gate and the recommended action. Approval records the decision and does not execute the change from that inbox. The old second frontend is not part of this repo. Chat's own Azure helper still uses HTTP and is not part of the sandbox audit.

The catalog the console shows is compute, data, network, and platform. It does not list every Azure resource type in the tenant.

Remote: `https://github.com/raghavrallan/infralens.git`. The console and the engine are this repository.
