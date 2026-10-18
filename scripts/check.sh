#!/usr/bin/env bash
set -euo pipefail
repo_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo_dir/backend"
.venv/bin/ruff check app tests alembic
.venv/bin/python -m pytest -q
.venv/bin/alembic check
cd "$repo_dir/frontend"
npm run typecheck
npm run build
