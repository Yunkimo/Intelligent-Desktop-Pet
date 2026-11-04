"""启动隔离服务并驱动真实带伞提醒 JavaScript/HTTP/数据库；任何断言失败即非零退出。

依赖 B 的天气订阅后端（weather-subscriptions.md 契约的 /api/weather/subscriptions 系列）。
B 未合入仓库时本脚本检测到路由缺失即跳过并退出 0（CI 保持绿色），合入后自动生效；
部署在云端的后端可用于真机验证，但本脚本只用本地隔离环境。
"""

import os
import secrets
import shutil
import socket
import subprocess
import sys
import tempfile
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

import httpx


@contextmanager
def temporary_test_dir() -> Iterator[str]:
    """等待 Windows 释放刚关闭的服务日志后再清理测试目录。"""
    directory = tempfile.mkdtemp(prefix="weather-test-")
    try:
        yield directory
    finally:
        for attempt in range(50):
            try:
                shutil.rmtree(directory)
                break
            except PermissionError:
                if attempt == 49:
                    raise
                time.sleep(0.1)


def main() -> int:
    """运行集成回归并始终关闭子进程、清理临时数据库。"""
    root = Path(__file__).resolve().parents[1]
    node = os.environ.get("NODE_BINARY") or shutil.which("node")
    if not node:
        raise RuntimeError("需要 Node 22+，可通过 NODE_BINARY 指定路径")
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    with temporary_test_dir() as directory:
        env = os.environ.copy()
        env.update(
            PYTHONPATH=str(root / "backend"),
            PYTHONUTF8="1",
            API_TOKEN=secrets.token_hex(24),
            DB_PATH=str(Path(directory) / "test.db"),
            SCHEDULER_ENABLED="false",
            WX_ENABLED="true",
            WX_APPID="test-app",
            WX_SECRET=secrets.token_hex(24),
            WX_TEMPLATE_ID="test",
            WX_TEMPLATE_FIELDS='{"thing1":"title","time2":"remind_at"}',
            WX_TEMPLATE_DATE_FIELDS="[]",
            LLM_API_KEY="",
            WEATHER_TEST_PORT=str(port),
            TZ="Asia/Shanghai",
        )
        with (Path(directory) / "server.log").open("w", encoding="utf-8") as log:
            process = subprocess.Popen(
                [sys.executable, str(root / "scripts/weather_test_server.py")],
                cwd=root,
                env=env,
                stdout=log,
                stderr=subprocess.STDOUT,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
            )
            try:
                for _ in range(100):
                    if process.poll() is not None:
                        raise RuntimeError("带伞提醒测试服务启动失败")
                    try:
                        if (
                            httpx.get(
                                f"http://127.0.0.1:{port}/api/health", timeout=1, trust_env=False
                            ).status_code
                            == 200
                        ):
                            break
                    except httpx.HTTPError:
                        pass
                    time.sleep(0.1)
                else:
                    raise RuntimeError("带伞提醒测试服务启动超时")
                # B 的天气订阅后端未合入：路由缺失 → 明确跳过而不是冒充通过
                probe = httpx.post(
                    f"http://127.0.0.1:{port}/api/weather/subscriptions",
                    json={"city": "长沙"},
                    headers={"X-API-Key": env["API_TOKEN"]},
                    timeout=5,
                    trust_env=False,
                )
                if probe.status_code == 404:
                    print("SKIP: 后端尚无 /api/weather/subscriptions（B 未合入），跳过联调")
                    return 0
                return subprocess.run(
                    [node, str(root / "miniprogram/tests/weather-contract.test.js")],
                    cwd=root,
                    env=env,
                    timeout=180,
                ).returncode
            finally:
                process.terminate()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)


if __name__ == "__main__":
    sys.exit(main())
