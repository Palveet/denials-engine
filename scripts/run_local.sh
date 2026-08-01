#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_DIR"

if [[ ! -f .env ]]; then
  echo "Missing .env. Run: cp .env.example .env"
  echo "Then add ANTHROPIC_API_KEY and the exact LLM_MODEL ID to .env and run this script again."
  exit 1
fi

if ! grep -Eq '^ANTHROPIC_API_KEY=[^[:space:]].*$' .env; then
  echo "ANTHROPIC_API_KEY is empty in .env. Add your real Anthropic key first."
  exit 1
fi

if ! grep -Eq '^(LLM_MODEL|ANTHROPIC_MODEL)=[^[:space:]].*$' .env; then
  echo "LLM_MODEL is empty in .env. Add the exact model ID supported by your provider."
  exit 1
fi

if [[ ! -x .venv/bin/python ]]; then
  if ! command -v python3.12 >/dev/null 2>&1; then
    echo "Python 3.12 is required. Install it, then run this script again."
    exit 1
  fi
  python3.12 -m venv .venv
fi

if [[ ! -x .venv/bin/uvicorn ]]; then
  .venv/bin/pip install -r requirements.txt
fi

if ! command -v npm >/dev/null 2>&1; then
  echo "Node.js/npm is required. Install Node.js, then run this script again."
  exit 1
fi

if [[ ! -d frontend/node_modules ]]; then
  (cd frontend && npm install)
fi

(cd frontend && npm run build:app)

echo "Starting Mini Denials at http://127.0.0.1:${APP_PORT:-3000}"
exec .venv/bin/uvicorn app.main:app \
  --host 127.0.0.1 \
  --port "${APP_PORT:-3000}" \
  --env-file .env
