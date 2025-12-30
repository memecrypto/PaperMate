#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

log() {
  printf "[dev] %s\n" "$*"
}

start_infra() {
  if [[ "${SKIP_INFRA:-0}" == "1" ]]; then
    log "Skipping infra (SKIP_INFRA=1)."
    return
  fi

  if command -v docker-compose >/dev/null 2>&1; then
    log "Starting db via docker-compose."
    (cd "$ROOT_DIR" && docker-compose up -d db)
  elif command -v docker >/dev/null 2>&1; then
    log "Starting db via docker compose."
    (cd "$ROOT_DIR" && docker compose up -d db)
  else
    log "Docker not found; skipping db."
  fi
}

pick_python() {
  if [[ -x "$ROOT_DIR/backend/.venv/bin/python" ]]; then
    echo "$ROOT_DIR/backend/.venv/bin/python"
    return
  fi
  if command -v python >/dev/null 2>&1; then
    command -v python
    return
  fi
  if command -v python3 >/dev/null 2>&1; then
    command -v python3
    return
  fi
  return 1
}

start_backend() {
  if [[ "${SKIP_BACKEND:-0}" == "1" ]]; then
    log "Skipping backend (SKIP_BACKEND=1)."
    return
  fi

  local py
  if ! py="$(pick_python)"; then
    log "Python not found. Activate a venv or install Python 3.11+."
    exit 1
  fi

  if ! "$py" -c "import uvicorn" >/dev/null 2>&1; then
    log "uvicorn not available. Install backend deps: (cd backend && pip install -e .)"
    exit 1
  fi

  if [[ ! -f "$ROOT_DIR/backend/.env" ]]; then
    log "Missing backend/.env. Copy backend/.env.example and configure it."
    exit 1
  fi

  if [[ "${SKIP_MIGRATIONS:-0}" != "1" ]]; then
    log "Running database migrations."
    (cd "$ROOT_DIR/backend" && "$py" -m alembic upgrade head)
  else
    log "Skipping migrations (SKIP_MIGRATIONS=1)."
  fi

  log "Starting backend on http://localhost:8000."
  (cd "$ROOT_DIR/backend" && "$py" -m uvicorn app.main:app --reload --port 8000) &
  BACKEND_PID=$!
}

start_frontend() {
  if [[ "${SKIP_FRONTEND:-0}" == "1" ]]; then
    log "Skipping frontend (SKIP_FRONTEND=1)."
    return
  fi

  if ! command -v npm >/dev/null 2>&1; then
    log "npm not found. Install Node.js 18+."
    exit 1
  fi

  if [[ ! -d "$ROOT_DIR/frontend/node_modules" ]]; then
    log "Installing frontend dependencies."
    (cd "$ROOT_DIR/frontend" && npm install)
  fi

  log "Starting frontend on http://localhost:5173."
  (cd "$ROOT_DIR/frontend" && npm run dev) &
  FRONTEND_PID=$!
}

cleanup() {
  if [[ -n "${FRONTEND_PID:-}" ]]; then
    kill "$FRONTEND_PID" >/dev/null 2>&1 || true
  fi
  if [[ -n "${BACKEND_PID:-}" ]]; then
    kill "$BACKEND_PID" >/dev/null 2>&1 || true
  fi
}

trap cleanup EXIT INT TERM

start_infra
start_backend
start_frontend

wait
