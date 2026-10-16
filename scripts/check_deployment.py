"""部署自检：健康检查、鉴权 REST 与 WebSocket 握手（见 docs/deploy.md）。

在 backend 虚拟环境运行：
    backend/.venv/Scripts/python scripts/check_deployment.py [BASE_URL]

BASE_URL 默认 http://127.0.0.1:8001；API_TOKEN 从 backend/.env 读取。
任一检查失败以非零状态退出。WS 握手仅验证 101 与鉴权拒绝，不消费业务事件。
"""

import argparse
import sys
from pathlib import Path

import httpx
from dotenv import load_dotenv
from websockets.sync.client import connect

ROOT = Path(__file__).resolve().parents[1]

load_dotenv(ROOT / "backend" / ".env")
import os  # noqa: E402

TOKEN = os.getenv("API_TOKEN", "")
if not TOKEN:
    print("FAIL 未配置 API_TOKEN（backend/.env）")
    sys.exit(1)

checks: list[tuple[str, bool]] = []


def record(name: str, ok: bool, detail: str = "") -> None:
    checks.append((name, ok))
    print(f"{'PASS' if ok else 'FAIL'} {name}" + (f"：{detail}" if detail else ""))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("base_url", nargs="?", default="http://127.0.0.1:8001")
    args = parser.parse_args()
    base = args.base_url.rstrip("/")

    # 1. 健康检查
    try:
        health = httpx.get(f"{base}/api/health", timeout=5)
        record(
            "GET /api/health 返回 200",
            health.status_code == 200 and health.json() == {"status": "ok"},
        )
    except httpx.HTTPError as exc:
        record("GET /api/health 返回 200", False, str(exc))
        sys.exit(1)

    # 2. 鉴权 REST：无 Key 拒绝、正确 Key 放行
    try:
        no_key = httpx.get(f"{base}/api/courses", timeout=5)
        record(
            "无 X-API-Key 被拒绝（401）", no_key.status_code == 401, f"实际 {no_key.status_code}"
        )
    except httpx.HTTPError as exc:
        record("无 X-API-Key 被拒绝（401）", False, str(exc))
    try:
        with_key = httpx.get(f"{base}/api/courses", headers={"X-API-Key": TOKEN}, timeout=5)
        record(
            "正确 X-API-Key 放行（200）",
            with_key.status_code == 200,
            f"实际 {with_key.status_code}",
        )
    except httpx.HTTPError as exc:
        record("正确 X-API-Key 放行（200）", False, str(exc))

    # 3. WebSocket：正确 token 握手 101；缺失/错误 token 被拒绝
    ws_ok = False
    try:
        with connect(f"ws://{base.split('://', 1)[1]}/ws?token={TOKEN}", open_timeout=5) as ws:
            ws_ok = ws.response.status_code == 101
        record("WS 正确 token 握手 101", ws_ok)
    except Exception as exc:  # noqa: BLE001
        record("WS 正确 token 握手 101", False, str(exc))
    try:
        connect(f"ws://{base.split('://', 1)[1]}/ws?token=wrong", open_timeout=5)
        record("WS 错误 token 被拒绝", False, "错误 token 竟然握手成功")
    except Exception:  # noqa: BLE001
        record("WS 错误 token 被拒绝", True)

    failed = [name for name, ok in checks if not ok]
    print(f"\n结果：{len(checks) - len(failed)}/{len(checks)} 通过")
    if failed:
        sys.exit(1)


if __name__ == "__main__":
    main()
