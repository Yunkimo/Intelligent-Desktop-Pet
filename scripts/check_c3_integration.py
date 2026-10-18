"""启动隔离服务并驱动真实 C3 JavaScript/HTTP/数据库；任何断言失败即非零退出。"""

import json
import os
import secrets
import shutil
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import httpx


def main() -> int:
    """运行集成回归并始终关闭子进程、清理临时数据库。"""
    root = Path(__file__).resolve().parents[1]
    node = os.environ.get("NODE_BINARY") or shutil.which("node")
    if not node:
        raise RuntimeError("需要 Node 22+，可通过 NODE_BINARY 指定路径")
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    with tempfile.TemporaryDirectory(prefix="c3-test-") as directory:
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
            WX_TEMPLATE_FIELDS=json.dumps({"thing1": "title", "time2": "remind_at"}),
            C3_TEST_PORT=str(port),
            TZ="Asia/Shanghai",
            LLM_API_KEY="",
        )
        with (Path(directory) / "server.log").open("w", encoding="utf-8") as log:
            process = subprocess.Popen(
                [sys.executable, str(root / "scripts/c3_test_server.py")],
                cwd=root,
                env=env,
                stdout=log,
                stderr=subprocess.STDOUT,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
            )
            try:
                for _ in range(100):
                    if process.poll() is not None:
                        raise RuntimeError("C3 测试服务启动失败")
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
                    raise RuntimeError("C3 测试服务启动超时")
                return subprocess.run(
                    [node, str(root / "miniprogram/tests/subscribe-contract.test.js")],
                    cwd=root,
                    env=env,
                    timeout=90,
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
