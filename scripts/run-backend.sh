#!/usr/bin/env bash
# 后端启动脚本（Linux/macOS 本地开发路线，见 docs/deploy.md）。
# 用法：./scripts/run-backend.sh [PORT] [SCHEDULER_INTERVAL_SECONDS]
set -euo pipefail

PORT="${1:-8001}"
INTERVAL="${2:-30}"

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BACKEND="$ROOT/backend"
VENV="$BACKEND/.venv"
PYTHON="$VENV/bin/python"

if [ ! -x "$PYTHON" ]; then
  echo "[run-backend] 创建虚拟环境 backend/.venv ..."
  python3 -m venv "$VENV"
fi

if [ ! -f "$VENV/.deps-installed" ]; then
  echo "[run-backend] 安装依赖 ..."
  "$PYTHON" -m pip install --disable-pip-version-check -q -r "$BACKEND/requirements.txt"
  touch "$VENV/.deps-installed"
fi

if [ ! -f "$BACKEND/.env" ]; then
  cp "$BACKEND/.env.example" "$BACKEND/.env"
  echo "[run-backend] 已从 .env.example 复制 backend/.env，请填入 API_TOKEN 后重新运行" >&2
  exit 1
fi

export SCHEDULER_INTERVAL_SECONDS="$INTERVAL"
echo "[run-backend] 启动后端：http://0.0.0.0:$PORT（单 worker，调度扫描 $INTERVAL 秒）"
exec "$PYTHON" -m uvicorn app.main:app --app-dir "$BACKEND" --host 0.0.0.0 --port "$PORT" --workers 1
