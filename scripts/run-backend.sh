#!/usr/bin/env bash
# 用法：bash scripts/run-backend.sh [PORT] [INTERVAL] [BIND_ADDRESS]
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BACKEND="$ROOT/backend"
VENV="$BACKEND/.venv"
PYTHON="$VENV/bin/python"
if [[ ! -x "$PYTHON" ]]; then
  python3 -m venv "$VENV"
fi
DIGEST="$("$PYTHON" -c 'import hashlib,sys; print(hashlib.sha256(open(sys.argv[1],"rb").read()).hexdigest())' "$BACKEND/requirements.txt")"
INSTALLED="$(cat "$VENV/.deps-sha256" 2>/dev/null || true)"
if [[ "$INSTALLED" != "$DIGEST" ]]; then
  "$PYTHON" -m pip install --disable-pip-version-check -r "$BACKEND/requirements.txt"
  printf '%s\n' "$DIGEST" > "$VENV/.deps-sha256"
fi
if [[ ! -f "$BACKEND/.env" ]]; then
  (umask 077; cp "$BACKEND/.env.example" "$BACKEND/.env")
  echo 'Created backend/.env. Set API_TOKEN before restarting.' >&2
  exit 1
fi
ARGS=(--port "${1:-8001}" --host "${3:-127.0.0.1}")
if [[ -n "${2:-}" ]]; then ARGS+=(--interval "$2"); fi
exec "$PYTHON" "$ROOT/scripts/run_backend.py" "${ARGS[@]}"