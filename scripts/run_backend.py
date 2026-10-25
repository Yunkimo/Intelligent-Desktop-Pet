"""本地启动入口：统一配置、相对数据库路径和失败退出码。"""

import argparse
import math
import os
import subprocess
import sys
from pathlib import Path

from dotenv import load_dotenv

BACKEND = Path(__file__).resolve().parents[1] / "backend"


def main() -> int:
    """启动单 worker；环境变量优先于 backend/.env。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8001)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--interval", type=float)
    args = parser.parse_args()
    load_dotenv(BACKEND / ".env")
    token = os.getenv("API_TOKEN", "").strip()
    if not token or token == "change-me-to-a-random-string":
        parser.error("请配置实际 API_TOKEN；拒绝空值和示例占位值")
    if not 1 <= args.port <= 65535:
        parser.error("port 必须在 1–65535 范围")
    if args.interval is not None:
        if not math.isfinite(args.interval) or args.interval <= 0:
            parser.error("interval 必须为正有限秒数")
        os.environ["SCHEDULER_INTERVAL_SECONDS"] = str(args.interval)
    configured = os.getenv("DB_PATH", "").strip()
    database = Path(configured) if configured else BACKEND / "data/pet.db"
    if not database.is_absolute():
        database = BACKEND / database
    os.environ["DB_PATH"] = str(database.resolve())
    return subprocess.call(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "app.main:app",
            "--host",
            args.host,
            "--port",
            str(args.port),
            "--workers",
            "1",
        ],
        cwd=BACKEND,
    )


if __name__ == "__main__":
    raise SystemExit(main())
