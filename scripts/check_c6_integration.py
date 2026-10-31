"""启动隔离服务并驱动真实 C6 JavaScript/HTTP/数据库；任何断言失败即非零退出。

依赖 B6 后端（PR #86 的 /api/semester 与 /api/calendar）。B6 未合入时本脚本
检测到路由缺失即跳过并退出 0，便于 CI 在 B6 合并前保持绿色；B6 合入后自动生效。
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
    directory = tempfile.mkdtemp(prefix="c6-test-")
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
    """运行集成回归并始终关闭子进程、清理临时数据库。

    默认启动仓库内的后端；B6 未合入时可用 BACKEND_DIR 指向含 /api/semester
    的后端目录（如 B 的开发分支检出），用于合入前的真实联调取证。
    """
    root = Path(__file__).resolve().parents[1]
    backend_dir = Path(os.environ.get("BACKEND_DIR", str(root / "backend")))
    node = os.environ.get("NODE_BINARY") or shutil.which("node")
    if not node:
        raise RuntimeError("需要 Node 22+，可通过 NODE_BINARY 指定路径")
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    with temporary_test_dir() as directory:
        env = os.environ.copy()
        env.update(
            PYTHONPATH=str(backend_dir),
            PYTHONUTF8="1",
            API_TOKEN=secrets.token_hex(24),
            DB_PATH=str(Path(directory) / "test.db"),
            SCHEDULER_ENABLED="false",
            WX_ENABLED="false",
            LLM_API_KEY="",
            C6_TEST_PORT=str(port),
            TZ="Asia/Shanghai",
        )
        with (Path(directory) / "server.log").open("w", encoding="utf-8") as log:
            process = subprocess.Popen(
                [sys.executable, str(root / "scripts/c6_test_server.py")],
                cwd=root,
                env=env,
                stdout=log,
                stderr=subprocess.STDOUT,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
            )
            try:
                for _ in range(100):
                    if process.poll() is not None:
                        raise RuntimeError("C6 测试服务启动失败")
                    try:
                        response = httpx.get(
                            f"http://127.0.0.1:{port}/api/health", timeout=1, trust_env=False
                        )
                        if response.status_code == 200:
                            break
                    except httpx.HTTPError:
                        pass
                    time.sleep(0.1)
                else:
                    raise RuntimeError("C6 测试服务启动超时")
                # B6 未合入：后端没有学期路由 → 明确跳过而不是冒充通过
                probe = httpx.get(
                    f"http://127.0.0.1:{port}/api/semester",
                    headers={"X-API-Key": env["API_TOKEN"]},
                    timeout=5,
                    trust_env=False,
                )
                if probe.status_code == 404:
                    print("SKIP: 后端尚无 /api/semester（B6 PR #86 未合入），跳过 C6 联调")
                    return 0
                return subprocess.run(
                    [node, str(root / "miniprogram/tests/semester-contract.test.js")],
                    cwd=root,
                    env=env,
                    timeout=120,
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
