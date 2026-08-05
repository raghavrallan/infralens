#!/usr/bin/env bash
# Restrict the GitHub Actions deploy key to rsync sync + deploy only.
# Any non-rsync SSH session runs gha-deploy.sh (no shell).
set -euo pipefail

case "${SSH_ORIGINAL_COMMAND:-}" in
  rsync\ --server*)
    # shellcheck disable=SC2086
    exec ${SSH_ORIGINAL_COMMAND}
    ;;
  *)
    exec /home/infralensmog/bin/gha-deploy.sh
    ;;
esac
