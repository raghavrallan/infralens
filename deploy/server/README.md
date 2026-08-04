# Server deploy (GitHub Actions → SSH + rsync)

Deploy uses a **deploy-only** SSH key. On the server that key is forced through
`gha-ssh-wrapper.sh`, which only allows:

1. `rsync --server ...` (code sync from Actions)
2. `deploy` (runs `gha-deploy.sh` → `docker compose up -d --build` + health check)

No interactive shell, no port forwarding.

GitHub → server is push-based (rsync). The server does **not** need outbound
git access to GitHub.

## Server layout

| Path | Purpose |
|------|---------|
| `~/apps/devsecops-skills-suite` | App tree (synced by Actions; `.env` never overwritten) |
| `~/bin/gha-deploy.sh` | Compose rebuild + health check |
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
```

## Trigger

Push to `master`, or **Actions → Deploy → Run workflow**.
