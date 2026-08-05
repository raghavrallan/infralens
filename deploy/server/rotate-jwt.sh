#!/usr/bin/env bash
set -euo pipefail
APP=~/apps/devsecops-skills-suite
ENV="$APP/.env"
JWT="$(python3 -c 'import secrets; print(secrets.token_urlsafe(48))')"

if grep -q '^AUTH_JWT_SECRET=' "$ENV"; then
  sed -i "s|^AUTH_JWT_SECRET=.*|AUTH_JWT_SECRET=${JWT}|" "$ENV"
else
  echo "AUTH_JWT_SECRET=${JWT}" >> "$ENV"
fi

grep -q '^EXECUTOR_SERVICE_KEY=' "$ENV" || echo 'EXECUTOR_SERVICE_KEY=dev-executor-key' >> "$ENV"

cd "$APP"
docker compose --profile container-app up -d api worker
sleep 4
curl -fsS http://127.0.0.1:62678/api/health
echo
echo "AUTH_JWT_SECRET length in .env: $(grep '^AUTH_JWT_SECRET=' .env | cut -d= -f2 | wc -c)"
echo "AUTH_JWT_SECRET length in api container: $(docker exec devsecops-api printenv AUTH_JWT_SECRET | wc -c)"
echo "AUTH_USERNAME in api: $(docker exec devsecops-api printenv AUTH_USERNAME)"
docker exec devsecops-postgres psql -U devsecops -d devsecops -c 'SELECT username, role FROM users;'
docker exec devsecops-postgres psql -U devsecops -d devsecops -c 'SELECT id, name, slug FROM organizations;'
