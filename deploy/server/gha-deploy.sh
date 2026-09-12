#!/usr/bin/env bash
# Deploy after GitHub Actions has rsync'd the tree into APP_DIR.
# Does not pull from GitHub (server outbound git SSH may be blocked).
# On-prem stack always includes n8n (mandatory for our server).
set -euo pipefail

APP_DIR="${APP_DIR:-$HOME/apps/devsecops-skills-suite}"
COMPOSE_PROFILE="${COMPOSE_PROFILE:-container-app}"
# Our server always requires n8n. Forks may set REQUIRE_N8N=false.
REQUIRE_N8N="${REQUIRE_N8N:-true}"

cd "$APP_DIR"

if [[ ! -f .env ]]; then
  echo "ERROR: missing $APP_DIR/.env (required for deploy)" >&2
  exit 1
fi

set -a
# shellcheck disable=SC1091
source .env
set +a

PROFILE_ARGS=(--profile "$COMPOSE_PROFILE")
if [[ "$REQUIRE_N8N" == "true" ]]; then
  if [[ -z "${N8N_ENCRYPTION_KEY:-}" ]]; then
    echo "ERROR: N8N_ENCRYPTION_KEY must be set in .env (on-prem n8n is mandatory)" >&2
    exit 1
  fi
  PROFILE_ARGS+=(--profile n8n)
fi

echo "==> Validating compose (profiles: ${PROFILE_ARGS[*]})"
docker compose "${PROFILE_ARGS[@]}" config >/dev/null

if [[ "$REQUIRE_N8N" == "true" ]]; then
  if ! docker compose "${PROFILE_ARGS[@]}" config --services | grep -qx "n8n"; then
    echo "ERROR: n8n service missing — on-prem n8n is mandatory" >&2
    exit 1
  fi
fi

echo "==> Building and restarting stack"
docker compose "${PROFILE_ARGS[@]}" up -d --build --remove-orphans

echo "==> Health check (API)"
API_PORT="${API_HOST_PORT:-8000}"
api_ok=0
for _ in $(seq 1 45); do
  if curl -fsS -m 3 "http://127.0.0.1:${API_PORT}/api/health" >/dev/null 2>&1; then
    curl -fsS -m 3 "http://127.0.0.1:${API_PORT}/api/health"
    echo
    api_ok=1
    break
  fi
  sleep 2
done
if [[ "$api_ok" != "1" ]]; then
  echo "ERROR: API health check failed after deploy" >&2
  docker compose "${PROFILE_ARGS[@]}" ps >&2 || true
  exit 1
fi

if [[ "$REQUIRE_N8N" == "true" ]]; then
  echo "==> Health check (n8n)"
  N8N_PORT="${N8N_HOST_PORT:-5678}"
  n8n_ok=0
  for _ in $(seq 1 45); do
    if curl -fsS -m 3 "http://127.0.0.1:${N8N_PORT}/healthz" >/dev/null 2>&1; then
      echo "n8n healthy on :${N8N_PORT}"
      n8n_ok=1
      break
    fi
    sleep 2
  done
  if [[ "$n8n_ok" != "1" ]]; then
    echo "ERROR: n8n health check failed after deploy (on-prem n8n is mandatory)" >&2
    docker compose "${PROFILE_ARGS[@]}" ps >&2 || true
    docker compose "${PROFILE_ARGS[@]}" logs --tail=80 n8n >&2 || true
    exit 1
  fi
fi

echo "==> Deploy OK"
exit 0
