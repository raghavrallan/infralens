#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
echo "==> Pylint (fail under 9.0)"
pylint app executors
echo "==> Tests + coverage (fail under 90%)"
pytest --cov=app --cov=executors --cov-branch --cov-report=term-missing --cov-report=html --cov-report=xml --cov-fail-under=90 --junitxml=junit.xml
