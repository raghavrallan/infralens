#!/usr/bin/env bash
# Deploy after GitHub Actions has rsync'd the tree into APP_DIR.
# Does not pull from GitHub (server outbound git SSH may be blocked).
set -euo pipefail

APP_DIR="${APP_DIR:-$HOME/apps/devsecops-skills-suite}"
COMPOSE_PROFILE="${COMPOSE_PROFILE:-container-app}"

cd "$APP_DIR"

if [[ ! -f .env ]]; then
  echo "ERROR: missing $APP_DIR/.env (required for deploy)" >&2
  exit 1
fi

set -a
# shellcheck disable=SC1091
source .env
set +a

echo "==> Building and restarting stack (profile=${COMPOSE_PROFILE})"
docker compose --profile "$COMPOSE_PROFILE" up -d --build --remove-orphans

echo "==> Health check"
API_PORT="${API_HOST_PORT:-8000}"
for _ in $(seq 1 45); do
  if curl -fsS -m 3 "http://127.0.0.1:${API_PORT}/api/health" >/dev/null 2>&1; then
    curl -fsS -m 3 "http://127.0.0.1:${API_PORT}/api/health"
    echo
    echo "==> Deploy OK"
    exit 0
  fi
  sleep 2
done

echo "ERROR: health check failed after deploy" >&2
docker compose --profile "$COMPOSE_PROFILE" ps >&2 || true
exit 1
