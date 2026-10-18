#!/usr/bin/env bash
set -euo pipefail
repo_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo_dir/backend"
.venv/bin/alembic upgrade head
api_pid= worker_pid= web_pid=
cleanup() {
  for service_pid in "$api_pid" "$worker_pid" "$web_pid"; do
    if [[ -n "$service_pid" ]]; then kill "$service_pid" 2>/dev/null || true; fi
  done
}
trap cleanup EXIT INT TERM
.venv/bin/uvicorn app.main:app --host 0.0.0.0 --port "${API_PORT:-8000}" & api_pid=$!
.venv/bin/python -m app.worker & worker_pid=$!
cd "$repo_dir/frontend"
NEXT_TELEMETRY_DISABLED=1 node node_modules/next/dist/bin/next dev --hostname 0.0.0.0 --port "${PORT:-3000}" & web_pid=$!
wait -n "$api_pid" "$worker_pid" "$web_pid"
