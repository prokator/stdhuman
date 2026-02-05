#!/usr/bin/env bash
set -euo pipefail

if [[ ! -d ".venv" ]]; then
  python -m venv .venv
fi

source .venv/bin/activate

python -m pip install -r requirements.txt

PORT="${PORT:-18081}"
uvicorn app.main:app --host 127.0.0.1 --port "$PORT"
