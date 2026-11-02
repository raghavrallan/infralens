#!/usr/bin/env bash
# Infralens - local run helper (Ubuntu / Linux)
#
# Counterpart of scripts/start-suite.ps1. The PowerShell script opens API and
# RQ worker in CMD windows and leaves the Next console as a separate
# `npm run dev`. This script starts the same services in the background and
# also starts the console, so one command runs the product.
#
# Usage (from anywhere):
#   ./scripts/start-suite.sh setup      # Python 3.13 venv, pip, npm
#   ./scripts/start-suite.sh start      # Postgres+Redis + API + worker + console
#   ./scripts/start-suite.sh seed       # shared admin + InfraLens + EQIP
#   ./scripts/start-suite.sh stop       # stop processes and Docker infra
#   ./scripts/start-suite.sh status
#   ./scripts/start-suite.sh restart
#
# Optional:
#   ./scripts/start-suite.sh start --skip-docker
#   ./scripts/start-suite.sh start --skip-console
#   ./scripts/start-suite.sh start --with-executors
#   ./scripts/start-suite.sh seed --reset-password

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

VENV_PYTHON="$ROOT/.venv/bin/python"
RUN_DIR="$ROOT/.local-run"
API_PID="$RUN_DIR/api.pid"
WORKER_PID="$RUN_DIR/worker.pid"
ESTATE_PID="$RUN_DIR/estate-worker.pid"
CONSOLE_PID="$RUN_DIR/console.pid"
API_LOG="$RUN_DIR/api.log"
WORKER_LOG="$RUN_DIR/worker.log"
ESTATE_LOG="$RUN_DIR/estate-worker.log"
CONSOLE_LOG="$RUN_DIR/console.log"

DEFAULT_DATABASE_URL="postgresql+psycopg2://devsecops:devsecops@localhost:5544/devsecops"
DEFAULT_REDIS_URL="redis://localhost:6399/0"
PYTHON_VERSION="3.13"

COMMAND="start"
SKIP_DOCKER=0
SKIP_CONSOLE=0
WITH_EXECUTORS=0
RESET_PASSWORD=0

usage() {
  sed -n '2,22p' "$0" | sed 's/^# \{0,1\}//'
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    setup|start|stop|restart|status|seed) COMMAND="$1" ;;
    --skip-docker) SKIP_DOCKER=1 ;;
    --skip-console) SKIP_CONSOLE=1 ;;
    --with-executors) WITH_EXECUTORS=1 ;;
    --reset-password) RESET_PASSWORD=1 ;;
    -h|--help) usage; exit 0 ;;
    *)
      echo "Unknown argument: $1" >&2
      usage >&2
      exit 1
      ;;
  esac
  shift
done

ensure_run_dir() {
  mkdir -p "$RUN_DIR"
}

load_dotenv() {
  local env_file="$ROOT/.env"
  if [[ ! -f "$env_file" && -f "$ROOT/.env.example" ]]; then
    cp "$ROOT/.env.example" "$env_file"
    echo "Created .env from .env.example"
  fi
  [[ -f "$env_file" ]] || return 0

  local line name value
  while IFS= read -r line || [[ -n "$line" ]]; do
    line="${line#"${line%%[![:space:]]*}"}"
    line="${line%"${line##*[![:space:]]}"}"
    [[ -z "$line" || "$line" == \#* ]] && continue
    [[ "$line" != *=* ]] && continue
    name="${line%%=*}"
    value="${line#*=}"
    name="${name%"${name##*[![:space:]]}"}"
    name="${name#"${name%%[![:space:]]*}"}"
    value="${value#"${value%%[![:space:]]*}"}"
    value="${value%"${value##*[![:space:]]}"}"
    if [[ ${#value} -ge 2 && ( "$value" == \"*\" || "$value" == \'*\' ) ]]; then
      value="${value:1:${#value}-2}"
    fi
    [[ -n "$name" ]] || continue
    export "$name=$value"
  done < "$env_file"
}

ensure_env_defaults() {
  export DATABASE_URL="${DATABASE_URL:-$DEFAULT_DATABASE_URL}"
  export REDIS_URL="${REDIS_URL:-$DEFAULT_REDIS_URL}"
  export EXECUTOR_SERVICE_KEY="${EXECUTOR_SERVICE_KEY:-dev-executor-key}"
  export APP_HOST="${APP_HOST:-0.0.0.0}"
  export APP_PORT="${APP_PORT:-8001}"
  export FRONTEND_HOST="${FRONTEND_HOST:-0.0.0.0}"
  export FRONTEND_PORT="${FRONTEND_PORT:-3001}"
  export CONTROL_PLANE_URL="${CONTROL_PLANE_URL:-http://127.0.0.1:${APP_PORT}}"
  export SUITE_API_UPSTREAM="${SUITE_API_UPSTREAM:-http://127.0.0.1:${APP_PORT}}"
  export DEV_API_ORIGIN="${DEV_API_ORIGIN:-http://127.0.0.1:${APP_PORT}}"
  case ":${PYTHONPATH:-}:" in
    *":${ROOT}/engine:"*) ;;
    *) export PYTHONPATH="${ROOT}/engine${PYTHONPATH:+:${PYTHONPATH}}" ;;
  esac
}

venv_minor() {
  "$VENV_PYTHON" -c 'import sys; print("%s.%s" % sys.version_info[:2])'
}

invoke_setup() {
  if ! command -v uv >/dev/null 2>&1; then
    echo "uv is required to create the suite virtualenv." >&2
    echo "Install it, then re-run: ./scripts/start-suite.sh setup" >&2
    exit 1
  fi
  if ! command -v npm >/dev/null 2>&1; then
    echo "npm is required for the Next.js console." >&2
    exit 1
  fi

  echo "==> Ensuring Python ${PYTHON_VERSION} for .venv"
  if [[ -x "$VENV_PYTHON" ]]; then
    local minor
    minor="$(venv_minor || true)"
    case "$minor" in
      3.12|3.13)
        echo "    Using existing Python ${minor} venv"
        ;;
      *)
        echo "    Existing .venv is Python ${minor:-unknown} - recreating with ${PYTHON_VERSION}"
        rm -rf "$ROOT/.venv"
        ;;
    esac
  fi

  if [[ ! -x "$VENV_PYTHON" ]]; then
    echo "    Creating .venv with Python ${PYTHON_VERSION}"
    uv venv --python "$PYTHON_VERSION" "$ROOT/.venv"
  fi

  local confirm
  confirm="$(venv_minor)"
  case "$confirm" in
    3.12|3.13) ;;
    *)
      echo "Expected .venv Python 3.12 or 3.13 but found ${confirm}." >&2
      exit 1
      ;;
  esac

  echo "==> Installing Python dependencies"
  uv pip install --python "$VENV_PYTHON" -r "$ROOT/requirements.txt"

  if [[ ! -d "$ROOT/node_modules" ]]; then
    echo "==> Installing Node dependencies"
    npm ci
  else
    echo "==> Node dependencies already installed"
  fi

  load_dotenv
  echo
  echo "Setup complete (Python ${confirm}). Next: ./scripts/start-suite.sh start"
}

assert_venv() {
  if [[ ! -x "$VENV_PYTHON" ]]; then
    echo "Virtualenv missing. Running setup first."
    invoke_setup
  fi
}

compose() {
  docker compose "$@"
}

start_infra() {
  if [[ "$SKIP_DOCKER" -eq 1 ]]; then
    echo "==> Skipping Docker infra (--skip-docker). Expecting local Postgres and Redis."
    return 0
  fi
  if ! command -v docker >/dev/null 2>&1; then
    echo "Docker not found. Install Docker, or use: ./scripts/start-suite.sh start --skip-docker" >&2
    exit 1
  fi

  echo "==> Starting Postgres + Redis (Docker)"
  if ! compose up -d postgres redis; then
    echo "==> Compose start failed; recreating postgres/redis"
    compose down --remove-orphans || true
    compose up -d --force-recreate postgres redis
  fi

  echo "==> Waiting for Postgres..."
  local ready=0 i
  for i in $(seq 1 45); do
    if docker exec devsecops-postgres pg_isready -U devsecops -d devsecops >/dev/null 2>&1; then
      ready=1
      break
    fi
    sleep 1
  done
  if [[ "$ready" -ne 1 ]]; then
    echo "Postgres did not become ready in time." >&2
    exit 1
  fi

  echo "==> Waiting for Redis..."
  ready=0
  for i in $(seq 1 45); do
    if docker exec devsecops-redis redis-cli ping >/dev/null 2>&1; then
      ready=1
      break
    fi
    sleep 1
  done
  if [[ "$ready" -ne 1 ]]; then
    echo "Redis did not become ready in time." >&2
    exit 1
  fi
}

pid_alive() {
  local pidfile="$1"
  [[ -f "$pidfile" ]] || return 1
  local pid
  pid="$(tr -d '[:space:]' < "$pidfile")"
  [[ "$pid" =~ ^[0-9]+$ ]] || return 1
  kill -0 "$pid" 2>/dev/null
}

stop_pidfile() {
  local pidfile="$1"
  local label="$2"
  local quiet="${3:-0}"
  if [[ ! -f "$pidfile" ]]; then
    [[ "$quiet" -eq 1 ]] || echo "No saved ${label} pid."
    return 0
  fi
  local pid
  pid="$(tr -d '[:space:]' < "$pidfile" || true)"
  if [[ "$pid" =~ ^[0-9]+$ ]] && kill -0 "$pid" 2>/dev/null; then
    kill -- "-$pid" 2>/dev/null || kill "$pid" 2>/dev/null || true
    local i
    for i in 1 2 3 4 5; do
      kill -0 "$pid" 2>/dev/null || break
      sleep 0.4
    done
    if kill -0 "$pid" 2>/dev/null; then
      kill -9 -- "-$pid" 2>/dev/null || kill -9 "$pid" 2>/dev/null || true
    fi
    [[ "$quiet" -eq 1 ]] || echo "Stopped ${label} (pid ${pid})"
  else
    [[ "$quiet" -eq 1 ]] || echo "${label} process already exited (pid ${pid:-unknown})"
  fi
  rm -f "$pidfile"
}

stop_matching() {
  local pattern="$1"
  local label="$2"
  local pids
  pids="$(pgrep -f "$pattern" || true)"
  [[ -n "$pids" ]] || return 0
  local pid self
  self="$$"
  for pid in $pids; do
    [[ "$pid" -eq "$self" ]] && continue
    # Skip this script and the shell that launched it.
    if [[ -r "/proc/$pid/cmdline" ]] && tr '\0' ' ' < "/proc/$pid/cmdline" | grep -q "start-suite.sh"; then
      continue
    fi
    echo "    Stopping ${label} pid ${pid}"
    kill "$pid" 2>/dev/null || true
  done
}

stop_app() {
  local quiet="${1:-0}"
  stop_pidfile "$API_PID" "API" "$quiet"
  stop_pidfile "$WORKER_PID" "worker" "$quiet"
  stop_pidfile "$ESTATE_PID" "estate worker" "$quiet"
  stop_pidfile "$CONSOLE_PID" "console" "$quiet"
  stop_matching "${ROOT}/scripts/run_local_api.py" "API"
  stop_matching "rq.cli worker intelligence" "worker"
  stop_matching "app.estate.celery_app" "estate worker"
  stop_matching "${ROOT}/node_modules/next/dist/bin/next dev" "console"
}

port_listening() {
  local port="$1"
  ss -ltn 2>/dev/null | awk -v p=":${port}" '$4 ~ p"$" { found=1 } END { exit found ? 0 : 1 }'
}

pick_listen_port() {
  local preferred="$1"
  shift
  local candidate
  for candidate in "$preferred" "$@"; do
    if ! port_listening "$candidate"; then
      printf '%s\n' "$candidate"
      return 0
    fi
  done
  return 1
}

lan_addresses() {
  hostname -I 2>/dev/null | tr ' ' '\n' | grep -E '^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$' | grep -vE '^(127\.|172\.(1[6-9]|2[0-9]|3[0-1])\.)' || true
}

wait_http() {
  local url="$1"
  local label="$2"
  local timeout="${3:-45}"
  echo "==> Waiting for ${label} at ${url}"
  local deadline=$((SECONDS + timeout))
  local code
  while (( SECONDS < deadline )); do
    code="$(curl -s -o /dev/null -w "%{http_code}" --max-time 2 "$url" || true)"
    if [[ "$code" =~ ^[1-4][0-9][0-9]$ ]]; then
      echo "    ${label} is up (${code})"
      return 0
    fi
    sleep 0.8
  done
  echo "    WARNING: ${label} did not become ready within ${timeout}s"
  return 1
}

start_bg() {
  local name="$1"
  local pidfile="$2"
  local logfile="$3"
  shift 3
  : > "$logfile"
  setsid "$@" >>"$logfile" 2>&1 < /dev/null &
  local pid=$!
  echo "$pid" > "$pidfile"
  echo "    ${name} pid ${pid} (log ${logfile#"$ROOT"/})"
}

start_app() {
  assert_venv
  if [[ "$SKIP_CONSOLE" -eq 0 && ! -d "$ROOT/node_modules" ]]; then
    echo "==> Installing Node dependencies"
    npm ci
  fi
  load_dotenv
  ensure_env_defaults
  ensure_run_dir
  stop_app 1

  # Listen on every interface. 0.0.0.0 is not a URL the proxy or health
  # check can call, so those stay on loopback.
  export APP_HOST="0.0.0.0"
  export FRONTEND_HOST="0.0.0.0"

  local port
  if ! port="$(pick_listen_port "$APP_PORT" 8001 8002 8010 8080 8800)"; then
    echo "No free API port among ${APP_PORT}, 8001, 8002, 8010, 8080, 8800." >&2
    exit 1
  fi
  if [[ "$port" != "$APP_PORT" ]]; then
    echo "==> Port ${APP_PORT} is in use. Using API port ${port}."
  fi
  if [[ "$SKIP_CONSOLE" -eq 0 ]] && port_listening "${FRONTEND_PORT}"; then
    echo "Port ${FRONTEND_PORT} is already in use. Stop the other process or pass --skip-console." >&2
    ss -ltnp 2>/dev/null | awk -v p=":${FRONTEND_PORT}" '$4 ~ p"$"' || true
    exit 1
  fi

  export APP_PORT="$port"
  export CONTROL_PLANE_URL="http://127.0.0.1:${port}"
  export SUITE_API_UPSTREAM="http://127.0.0.1:${port}"
  export DEV_API_ORIGIN="http://127.0.0.1:${port}"

  local addresses address
  addresses="$(lan_addresses | paste -sd, -)"
  if [[ -n "$addresses" ]]; then
    export ALLOWED_DEV_ORIGINS="$addresses"
    address="$(lan_addresses | head -n 1)"
    case "${PUBLIC_APP_URL:-}" in
      ""|http://127.0.0.1:*|http://localhost:*)
        export PUBLIC_APP_URL="http://${address}:${FRONTEND_PORT}"
        ;;
    esac
    case "${OAUTH_REDIRECT_BASE:-}" in
      ""|http://127.0.0.1:*|http://localhost:*)
        export OAUTH_REDIRECT_BASE="http://${address}:${port}"
        ;;
    esac
  fi

  echo "==> Starting API, workers$([[ "$SKIP_CONSOLE" -eq 0 ]] && echo ", and Next console")"
  start_bg "API" "$API_PID" "$API_LOG" \
    "$VENV_PYTHON" "$ROOT/scripts/run_local_api.py"
  start_bg "worker" "$WORKER_PID" "$WORKER_LOG" \
    "$VENV_PYTHON" -m rq.cli worker intelligence \
    --worker-class app.intelligence.worker.Worker \
    --url "$REDIS_URL"
  start_bg "estate worker" "$ESTATE_PID" "$ESTATE_LOG" \
    "$VENV_PYTHON" -m celery -A app.estate.celery_app worker --beat --loglevel=info -Q estate --concurrency=2
  if [[ "$SKIP_CONSOLE" -eq 0 ]]; then
    start_bg "console" "$CONSOLE_PID" "$CONSOLE_LOG" \
      "$ROOT/node_modules/.bin/next" dev --hostname 0.0.0.0 --port "$FRONTEND_PORT"
  fi

  local api_ready=0
  if wait_http "http://127.0.0.1:${port}/api/health" "API" 45; then
    api_ready=1
  fi
  if [[ "$SKIP_CONSOLE" -eq 0 ]]; then
    wait_http "http://127.0.0.1:${FRONTEND_PORT}" "console" 90 || true
  fi

  if [[ "$WITH_EXECUTORS" -eq 1 ]]; then
    echo "==> Starting provider executors (Docker)"
    docker compose -f docker-compose.local-executors.yml up --build -d
  fi

  echo
  echo "Stack is listening on 0.0.0.0."
  echo "  API:      http://127.0.0.1:${port}"
  echo "  API log:  ${API_LOG#"$ROOT"/}"
  echo "  Worker:   ${WORKER_LOG#"$ROOT"/}"
  if [[ "$SKIP_CONSOLE" -eq 0 ]]; then
    echo "  Console:  http://127.0.0.1:${FRONTEND_PORT}"
    echo "  UI log:   ${CONSOLE_LOG#"$ROOT"/}"
  else
    echo "  Console:  skipped (--skip-console)"
  fi
  if [[ -n "${addresses:-}" ]]; then
    local shown
    while IFS= read -r shown; do
      [[ -n "$shown" ]] || continue
      echo "  From another machine:"
      echo "    Console  http://${shown}:${FRONTEND_PORT}"
      echo "    API      http://${shown}:${port}"
    done < <(lan_addresses)
  fi
  if [[ "$api_ready" -ne 1 ]]; then
    echo "  WARNING: API health check did not succeed yet. See ${API_LOG#"$ROOT"/}"
  fi
  echo
  echo "Stop with: ./scripts/start-suite.sh stop"
}

invoke_stop() {
  echo "==> Stopping local API, worker, and console"
  load_dotenv || true
  ensure_env_defaults
  stop_app 0

  if [[ "$SKIP_DOCKER" -eq 0 ]] && command -v docker >/dev/null 2>&1; then
    echo "==> Stopping Docker infra (postgres/redis)"
    compose stop postgres redis >/dev/null 2>&1 || true
    if [[ -f "$ROOT/docker-compose.local-executors.yml" ]]; then
      docker compose -f docker-compose.local-executors.yml down >/dev/null 2>&1 || true
    fi
  fi
  echo "Stopped."
}

show_proc() {
  local label="$1"
  local pidfile="$2"
  if pid_alive "$pidfile"; then
    printf "%-18s running (pid %s)\n" "${label}:" "$(tr -d '[:space:]' < "$pidfile")"
  else
    printf "%-18s not running\n" "${label}:"
  fi
}

invoke_status() {
  echo "Project: ${ROOT}"
  echo
  if [[ -x "$VENV_PYTHON" ]]; then
    echo "venv:              ok ($(venv_minor))"
  else
    echo "venv:              missing (run setup)"
  fi
  if [[ -d "$ROOT/node_modules" ]]; then
    echo "node_modules:      ok"
  else
    echo "node_modules:      missing (run setup)"
  fi
  echo
  show_proc "API" "$API_PID"
  show_proc "Worker" "$WORKER_PID"
  show_proc "Console" "$CONSOLE_PID"
  if command -v docker >/dev/null 2>&1; then
    echo
    echo "Docker containers:"
    docker ps --filter "name=devsecops-" --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}"
  fi
}

invoke_seed() {
  load_dotenv
  ensure_env_defaults
  assert_venv
  if [[ "$SKIP_DOCKER" -eq 0 ]]; then
    start_infra
  fi
  echo "Seeding shared admin + InfraLens org + EQIP project (Azure/GitHub)..."
  local -a args=("scripts/seed_shared_tenant.py")
  if [[ "$RESET_PASSWORD" -eq 1 ]]; then
    args+=("--reset-password")
  fi
  "$VENV_PYTHON" "${args[@]}"
}

case "$COMMAND" in
  setup) invoke_setup ;;
  start)
    start_infra
    start_app
    ;;
  stop) invoke_stop ;;
  restart)
    invoke_stop
    sleep 1
    start_infra
    start_app
    ;;
  status) invoke_status ;;
  seed) invoke_seed ;;
esac
