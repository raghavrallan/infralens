# On-prem n8n (mandatory for InfraLens server)

## Containers vs libraries

| Component | Runs as | Notes |
|-----------|---------|--------|
| **LangChain / LangGraph** | Inside `api` + `worker` images | Python packages in `requirements.txt` — **no separate container** |
| **n8n** | Dedicated `n8n` container | **Required** on our on-prem `container-app` deploy |

## Start (our server / full stack)

```bash
docker compose --profile container-app up -d --build
```

`n8n` is part of `container-app`. Server deploy auto-generates `N8N_ENCRYPTION_KEY` into `.env` if missing.

Requires in `.env`:

- `AUTH_JWT_SECRET`
- `N8N_ENCRYPTION_KEY`
- Prefer `N8N_WEBHOOKS_ENABLED=true` (compose default)
- `N8N_WEBHOOK_URL=http://n8n:5678/webhook/infralens`
- `INTEGRATIONS_API_KEY` for inbound decide/run from n8n

## Optional skip (forks only — not our server)

```bash
docker compose -f docker-compose.yml -f docker-compose.without-n8n.yml \
  --profile container-app up -d --build
```

## First-time n8n setup

1. Open `http://<host>:${N8N_HOST_PORT:-5678}`
2. Create owner account
3. Import `docs/integrations/n8n/approvals-slack.json`
4. Ensure Webhook path is `infralens` (matches `N8N_WEBHOOK_URL`)
5. Activate workflow
6. `POST /api/integrations/webhooks/test` with Bearer `INTEGRATIONS_API_KEY` or JWT

## Events InfraLens sends

- `approval.created` / `approval.decided`
- `delivery.stage_changed`
- `architecture.ready_for_accept`
- `workflow.run_completed`
