# Server deploy (GitHub Actions → SSH + rsync)

Deploy uses a **deploy-only** SSH key. On the server that key is forced through
`gha-ssh-wrapper.sh`, which only allows:

1. `rsync --server ...` (code sync from Actions)
2. `deploy` (runs `gha-deploy.sh` → `docker compose up -d --build` + health check)

No interactive shell, no port forwarding.

GitHub → server is push-based (rsync). The server does **not** need outbound
git access to GitHub.

## On-prem stack (mandatory)

`container-app` profile always includes:

- `api`, `worker`, provider executors
- **`n8n`** (on-prem automation — required for our server)

`gha-deploy.sh` always enables `--profile container-app --profile n8n` and fails if:

- `N8N_ENCRYPTION_KEY` is missing from `.env`
- n8n service is not in the compose profile set
- `/api/health` or n8n `/healthz` does not become healthy

Forks that want to skip n8n (not our server):

```bash
# omit n8n profile
docker compose --profile container-app up -d --build

# or disable webhook env via override
docker compose -f docker-compose.yml -f docker-compose.without-n8n.yml \
  --profile container-app up -d --build
```

## Server layout

| Path | Purpose |
|------|---------|
| `~/apps/devsecops-skills-suite` | App tree (synced by Actions; `.env` never overwritten) |
| `~/bin/gha-deploy.sh` | Compose rebuild + API/n8n health check |
| `~/bin/gha-ssh-wrapper.sh` | Forced-command gate for the deploy key |
| `~/.ssh/authorized_keys` | Deploy key entry with `command=...wrapper` |

## GitHub Actions secrets

| Secret | Example |
|--------|---------|
| `DEPLOY_HOST` | `10.8.14.78` or public IP / domain once DNS points here |
| `DEPLOY_PORT` | `64678` |
| `DEPLOY_USER` | `infralensmog` |
| `DEPLOY_PATH` | `/home/infralensmog/apps/devsecops-skills-suite/` |
| `DEPLOY_SSH_KEY` | Full private key for `gha_deploy` (`BEGIN`/`END` lines) |

## `.env` host ports (server)

```
POSTGRES_HOST_PORT=63678
REDIS_HOST_PORT=61678
API_HOST_PORT=62678
N8N_HOST_PORT=5678
N8N_ENCRYPTION_KEY=<long-random>
N8N_WEBHOOKS_ENABLED=true
N8N_WEBHOOK_URL=http://n8n:5678/webhook/infralens
WEBHOOK_HMAC_SECRET=<secret>
INTEGRATIONS_API_KEY=<secret>
```

After first deploy, open n8n UI, import `docs/integrations/n8n/approvals-slack.json`, and activate the webhook path `infralens`.

## Trigger

Push to `master`, or **Actions → Deploy → Run workflow**.

## CI quality gates (PRs)

Quality workflow requires: compose on-prem (n8n present), frontend typecheck, agent-runtime tests, pylint, unit tests, integration suite.
