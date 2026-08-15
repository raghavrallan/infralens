#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."

if [[ -z "${RUN_INFRA_TESTS:-}" && -f .env.test ]]; then
  RUN_INFRA_TESTS="$(grep -E '^RUN_INFRA_TESTS=' .env.test | tail -n1 | cut -d= -f2- | tr -d '[:space:]')"
  export RUN_INFRA_TESTS
fi

FAIL_UNDER=0
case "${RUN_INFRA_TESTS:-}" in
  1|true|TRUE|yes|YES|on|ON) FAIL_UNDER=90 ;;
esac

echo "==> Pylint (fail under 9.0)"
pylint app executors
echo "==> Tests + coverage (fail under ${FAIL_UNDER}%; RUN_INFRA_TESTS=${RUN_INFRA_TESTS:-})"
pytest --cov=app --cov=executors --cov-branch --cov-report=term-missing --cov-report=html --cov-report=xml --cov-fail-under="${FAIL_UNDER}" --junitxml=junit.xml
