# Infralens

One product. The Next.js console is the UI. The estate and the agentic side live in that same shell. The Python engine runs beside it.

An organization is a client. A person signs up and becomes the owner. Admins add people and attach projects. An Azure subscription belongs to one project. Inventory and cost reads stay inside that project's subscriptions.

There is no demo tenant and no generated spend.

## Run the console

```bash
npm install
npm run dev
```

Open http://localhost:3001. Create an organization, then connect an app registration under Organization.

`npm run check` verifies organization and project isolation without calling Azure.

## Run the agentic engine

Postgres and Redis:

```bash
docker compose up -d postgres redis
```

API, from the repo root:

```bash
python scripts/run_local_api.py
```

`npm run suite` is the same command. `.\scripts\start-suite.ps1 start` also starts the API. The script name is historical. The RQ worker is separate: `rq worker intelligence --worker-class app.intelligence.worker.Worker` with `PYTHONPATH=engine`. Workflows can be saved without that worker, and they do not execute until it is running.

The console is http://127.0.0.1:3001. The engine is http://127.0.0.1:8000. The browser calls `/suite-api/*`, which the Next app proxies to `http://127.0.0.1:8000/api/*`. That path is the proxy, not a second product.

Organization sign-in is the `il_session` cookie. The agentic engine still keeps its own JWT in the browser. They are not the same account yet.

## Azure app registration

Create an app registration and a client secret. On each subscription the client should expose, grant:

- Reader
- Cost Management Reader

Do not grant Owner. The app lists the subscriptions this identity can see. An admin attaches a subset to a project. Estate reads only those subscription IDs.

Reads use a client-credentials token, one Resource Graph query per connection, and Cost Management HTTP. The token is cached until near expiry. A snapshot younger than 60 seconds is served from memory. A snapshot younger than 15 minutes is shown immediately while a refresh runs. A cold Azure call is slower than that, because the wait is the Azure request.

The client secret is encrypted in `data/infralens.sqlite`. `data/` also holds the encryption key. Do not commit it.

## Roles

Organization owner and organization admin can connect Azure, create projects, and add members. They can read every project in that organization.

Project roles:

- Project admin, billing reader, and viewer can read inventory and cost.
- Operator can read inventory and cannot read cost.

A member of one project cannot open another project or another organization.

## What is in this repo

Console pages for cost, resources, virtual machines, storage, Container Apps, AKS, App Service, Databricks workspaces, Data Factory, metric alerts, Advisor, and the activity log.

Agentic pages in the same shell: chat, wiki, findings, workflows, approvals, architecture, engineering, and break-glass. Chat can run a skill in Agent mode or return steps in Plan mode. The default scope is read-only. Workflows enqueue a run when a cloud connection is present and the worker is up. Findings keep the gate and the recommended action. Approval records a decision and does not execute the change from that inbox. The Python package is `engine/app`. Import it as `app` with `PYTHONPATH=engine`. Executors, tests, and deploy files are in this repo. There is no second frontend.

## What is not done

Invoice PDF download. A single login for the organization cookie and the agentic engine JWT. A timed read against a live tenant. The root `Dockerfile` still has a frontend build stage that expects a `frontend/` directory this repo does not contain. Local development uses `npm run dev` and `scripts/run_local_api.py`, not that image.
