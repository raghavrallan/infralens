# Product understanding

Infralens is one product. The Next.js shell holds the Azure estate and the agentic side. There is no separate suite and no second frontend.

## Estate

An organization is the client. An Azure subscription belongs to one project. Estate pages read a saved Postgres snapshot: cost, resources, alerts, and Advisor, across compute, data, network, and platform. On-demand detail reads go through the Azure CLI sandbox and stay in Redis for one hour, keyed by resource. The product does not grant Azure RBAC.

## Agentic side

The engine is `engine/app`. The browser reaches it through `/suite-api`. That path is the proxy. The pages are chat, wiki, findings, workflows, approvals, architecture, engineering, and break-glass.

Chat has Agent and Plan. Agent runs a skill. Plan returns steps you can execute. The default scope is read-only: analyse and recommend, and label anything that would change a live system as a proposal. A write scope may draft a change and must not claim the change happened unless an executor result says so.

Workflows can be saved without the worker. They execute when the worker is running. Run now enqueues a job when Azure or AWS is connected. Findings are open items from those runs, with a gate and a recommended action. Architecture keeps Solution Architect runs and a delivery stage. Approving records the decision. The inbox does not execute the change.

Organization sign-in is the `il_session` cookie. The agentic engine still has its own JWT.

## Evidence

- `.ai/CURRENT_STATE.md`
- `.ai/PROJECT_CONTEXT.md`
- `README.md`
- `src/app/(console)/chat/page.js`
- `engine/app/chat/orchestrator.py`
- `src/app/(console)/workflows/page.js`
- `src/app/(console)/findings/page.js`
- `src/app/(console)/architecture/page.js`
- `src/app/(console)/approvals/page.js`
