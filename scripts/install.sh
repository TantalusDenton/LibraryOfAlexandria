#!/usr/bin/env bash
set -euo pipefail
repo_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export UV_CACHE_DIR="${UV_CACHE_DIR:-$repo_dir/.cache/uv}"
export npm_config_cache="${npm_config_cache:-$repo_dir/.cache/npm}"
export NEXT_TELEMETRY_DISABLED=1
cd "$repo_dir/backend"
uv sync --frozen --group dev
.venv/bin/alembic upgrade head
cd "$repo_dir/frontend"
npm ci --no-audit --no-fund
npm run build
