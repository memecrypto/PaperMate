#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

cd "$ROOT_DIR/backend" && python -m alembic upgrade head
cd "$ROOT_DIR/backend" && python -m uvicorn app.main:app --reload --port 8000 &
cd "$ROOT_DIR/frontend" && npm run dev &

wait
