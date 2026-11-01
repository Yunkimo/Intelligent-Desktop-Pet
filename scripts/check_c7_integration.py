"""启动隔离服务并驱动真实 C7 JavaScript/HTTP/数据库；任何断言失败即非零退出。

真实视觉模型调用不在 CI 执行（无 Key，模型端由 B7 验收）；parse-image 的错误映射
（503/401）与草稿→节次映射→批量落库→部分失败恢复的完整客户端链路均走真实后端与
临时 SQLite。B6 学期接口为课表页 load() 的前置（已合入 develop）。
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
    directory = tempfile.mkdtemp(prefix="c7-test-")
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
            WX_ENABLED="false",
            LLM_API_KEY="",
            C7_TEST_PORT=str(port),
            TZ="Asia/Shanghai",
        )
        with (Path(directory) / "server.log").open("w", encoding="utf-8") as log:
            process = subprocess.Popen(
                [sys.executable, str(root / "scripts/c7_test_server.py")],
                cwd=root,
                env=env,
                stdout=log,
                stderr=subprocess.STDOUT,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
            )
            try:
                for _ in range(100):
                    if process.poll() is not None:
                        raise RuntimeError("C7 测试服务启动失败")
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
                    raise RuntimeError("C7 测试服务启动超时")
                return subprocess.run(
                    [node, str(root / "miniprogram/tests/course-import-contract.test.js")],
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
