#!/usr/bin/env bash
# Install/refresh deploy-only SSH key + scripts (run as infralensmog).
set -euo pipefail

mkdir -p ~/bin ~/.ssh
chmod 700 ~/.ssh

install -m 755 /tmp/gha-deploy.sh ~/bin/gha-deploy.sh
install -m 755 /tmp/gha-ssh-wrapper.sh ~/bin/gha-ssh-wrapper.sh
sed -i 's/\r$//' ~/bin/gha-deploy.sh ~/bin/gha-ssh-wrapper.sh

FORCE='command="/home/infralensmog/bin/gha-ssh-wrapper.sh",no-port-forwarding,no-X11-forwarding,no-agent-forwarding,no-pty'
PUB="$(cat /tmp/gha_deploy.pub)"
touch ~/.ssh/authorized_keys
grep -v 'github-actions-deploy@infralens' ~/.ssh/authorized_keys > ~/.ssh/authorized_keys.tmp || true
mv ~/.ssh/authorized_keys.tmp ~/.ssh/authorized_keys
echo "${FORCE} ${PUB}" >> ~/.ssh/authorized_keys
chmod 600 ~/.ssh/authorized_keys

ensure_env() {
  local key="$1"
  local val="$2"
  local envf="$HOME/apps/devsecops-skills-suite/.env"
  [[ -f "$envf" ]] || return 0
  if grep -q "^${key}=" "$envf"; then
    sed -i "s|^${key}=.*|${key}=${val}|" "$envf"
  else
    echo "${key}=${val}" >> "$envf"
  fi
}
ensure_env POSTGRES_HOST_PORT 63678
ensure_env REDIS_HOST_PORT 61678
ensure_env API_HOST_PORT 62678

# Patch compose ports to env vars until master has them
COMPOSE="$HOME/apps/devsecops-skills-suite/docker-compose.yml"
if [[ -f "$COMPOSE" ]]; then
  sed -i 's/"[0-9]*:5432"/"${POSTGRES_HOST_PORT:-63678}:5432"/' "$COMPOSE"
  sed -i 's/"[0-9]*:6379"/"${REDIS_HOST_PORT:-61678}:6379"/' "$COMPOSE"
  sed -i 's/"[0-9]*:8000"/"${API_HOST_PORT:-62678}:8000"/' "$COMPOSE"
fi

echo "Deploy key entry:"
grep 'github-actions-deploy' ~/.ssh/authorized_keys | cut -c1-160
echo OK
