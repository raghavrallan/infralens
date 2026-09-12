#!/usr/bin/env bash
# Local parity with on-prem n8n bootstrap (Windows Git Bash / WSL / Linux).
# Fixes we hit on server: encryption key, secure cookie, webhook defaults, owner user.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

ensure_env_default() {
  local key="$1"
  local val="$2"
  if grep -q "^${key}=" .env 2>/dev/null; then
    return 0
  fi
  echo "${key}=${val}" >> .env
  echo "appended ${key}"
}

if [[ ! -f .env ]]; then
  echo "ERROR: create .env first (copy from .env.example)" >&2
  exit 1
fi

if ! grep -q '^N8N_ENCRYPTION_KEY=' .env || grep -q '^N8N_ENCRYPTION_KEY=replace-with-long-random-string$' .env || grep -q '^N8N_ENCRYPTION_KEY=infralens-onprem-n8n-change-me$' .env; then
  key="$(openssl rand -hex 24 2>/dev/null || head -c 48 /dev/urandom | od -An -tx1 | tr -d ' \n')"
  if grep -q '^N8N_ENCRYPTION_KEY=' .env; then
    # portable replace
    tmp="$(mktemp)"
    awk -v k="$key" 'BEGIN{FS=OFS="="} /^N8N_ENCRYPTION_KEY=/{print "N8N_ENCRYPTION_KEY="k; next} {print}' .env > "$tmp" && mv "$tmp" .env
  else
    echo "N8N_ENCRYPTION_KEY=${key}" >> .env
  fi
  echo "set N8N_ENCRYPTION_KEY"
fi

ensure_env_default N8N_WEBHOOKS_ENABLED true
ensure_env_default N8N_HOST_PORT 5678
ensure_env_default N8N_SECURE_COOKIE false
ensure_env_default N8N_PUBLIC_WEBHOOK_URL http://127.0.0.1:5678/
ensure_env_default N8N_EDITOR_BASE_URL http://127.0.0.1:5678/
ensure_env_default N8N_WEBHOOK_URL http://n8n:5678/webhook/infralens

echo "==> Starting n8n (container-app profile)"
docker compose --profile container-app up -d n8n

echo "==> Waiting for health"
for i in $(seq 1 30); do
  if curl -fsS -m 2 http://127.0.0.1:5678/healthz >/dev/null 2>&1; then
    echo "n8n healthy"
    break
  fi
  sleep 2
done
curl -fsS http://127.0.0.1:5678/healthz
echo

EMAIL="${N8N_OWNER_EMAIL:-raghavrallan@mooglelabs.com}"
PASS="${N8N_OWNER_PASSWORD:-Infralens@n8n1}"
FIRST="${N8N_OWNER_FIRST:-Raghav}"
LAST="${N8N_OWNER_LAST:-Rallan}"

PAYLOAD=$(printf '{"email":"%s","firstName":"%s","lastName":"%s","password":"%s"}' "$EMAIL" "$FIRST" "$LAST" "$PASS")
CODE=$(curl -sS -o /tmp/n8n_local_setup.json -w '%{http_code}' \
  -X POST http://127.0.0.1:5678/rest/owner/setup \
  -H 'Content-Type: application/json' \
  -d "$PAYLOAD" || true)
echo "owner setup HTTP ${CODE}"
if [[ "$CODE" != "200" && "$CODE" != "201" ]]; then
  echo "setup response:"; cat /tmp/n8n_local_setup.json || true; echo
  echo "(If already configured, login with existing owner.)"
else
  echo "Owner created: ${EMAIL}"
fi

echo
echo "Open: http://127.0.0.1:5678"
echo "Email: ${EMAIL}"
echo "Password: ${PASS}"
