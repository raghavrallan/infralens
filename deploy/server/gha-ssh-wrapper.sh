#!/usr/bin/env bash
# Restrict the GitHub Actions deploy key to rsync sync + deploy only.
# Prefer the rsynced deploy script so logic tracks the repo automatically.
set -euo pipefail

APP_DIR="${APP_DIR:-$HOME/apps/devsecops-skills-suite}"
REPO_DEPLOY="${APP_DIR}/deploy/server/gha-deploy.sh"

case "${SSH_ORIGINAL_COMMAND:-}" in
  rsync\ --server*)
    exec $SSH_ORIGINAL_COMMAND
    ;;
  deploy|"")
    if [[ -f "$REPO_DEPLOY" ]]; then
      # Keep ~/bin copy fresh for older callers, then run repo script.
      install -m 755 "$REPO_DEPLOY" "$HOME/bin/gha-deploy.sh" 2>/dev/null || true
      exec bash "$REPO_DEPLOY"
    fi
    exec "$HOME/bin/gha-deploy.sh"
    ;;
  *)
    echo "Rejected: only rsync --server and deploy are allowed" >&2
    exit 1
    ;;
esac
