"""C4 隔离测试：临时数据库、回环端口和自建 CA，不读取真实配置。"""

import os
import secrets
import shutil
import socket
import subprocess
import sys
import time
from contextlib import contextmanager
from pathlib import Path

import httpx
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
CREATE_FLAGS = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0


def free_port() -> int:
    """申请回环测试端口。"""
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def stop_process(process: subprocess.Popen) -> None:
    """只终止本测试创建的进程树。"""
    if process.poll() is None:
        if os.name == "nt":
            subprocess.run(
                ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                capture_output=True,
                timeout=10,
            )
        else:
            import signal

            os.killpg(process.pid, signal.SIGTERM)
        process.wait(timeout=10)


def run(args: list, env: dict, cwd: Path = ROOT, timeout: int = 30) -> subprocess.CompletedProcess:
    """合并采集脚本输出，不回显临时凭据。"""
    return subprocess.run(
        [str(arg) for arg in args],
        cwd=cwd,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
        creationflags=CREATE_FLAGS,
    )


@pytest.fixture
def isolated_env(tmp_path: Path) -> dict:
    """覆盖所有外部服务凭据，防止测试意外调用真实服务。"""
    return dict(
        os.environ,
        PYTHONUTF8="1",
        PYTHONIOENCODING="utf-8",
        API_TOKEN=secrets.token_hex(24) + "+/=?&",
        DB_PATH=str(tmp_path / "service.db"),
        WX_ENABLED="false",
        LLM_API_KEY="",
        LLM_BASE_URL="",
        LLM_VISION_MODEL="",
        SCHEDULER_ENABLED="true",
        SCHEDULER_INTERVAL_SECONDS="0.2",
    )


@contextmanager
def service(
    tmp_path: Path,
    env: dict,
    *,
    tls: tuple | None = None,
    args: list | None = None,
    port: int | None = None,
    cwd: Path = ROOT,
):
    """运行真实后端并等待就绪，退出时回收进程与日志句柄。"""
    port = port or free_port()
    command = args or [
        sys.executable,
        "-m",
        "uvicorn",
        "app.main:app",
        "--app-dir",
        ROOT / "backend",
        "--host",
        "127.0.0.1",
        "--port",
        port,
        "--workers",
        "1",
    ]
    verify = True
    if tls:
        import ssl

        cert, key = tls
        command += ["--ssl-certfile", cert, "--ssl-keyfile", key]
        verify = ssl.create_default_context(cafile=str(cert))
    base = f"{'https' if tls else 'http'}://127.0.0.1:{port}"
    log_path = tmp_path / f"backend-{port}.log"
    with log_path.open("w", encoding="utf-8") as log:
        process = subprocess.Popen(
            [str(arg) for arg in command],
            cwd=cwd,
            env=env,
            stdout=log,
            stderr=subprocess.STDOUT,
            creationflags=CREATE_FLAGS,
            start_new_session=os.name != "nt",
        )
        try:
            for _ in range(100):
                if process.poll() is not None:
                    raise RuntimeError("测试服务启动失败，检查临时后端日志")
                try:
                    if (
                        httpx.get(
                            base + "/api/health", timeout=0.5, trust_env=False, verify=verify
                        ).status_code
                        == 200
                    ):
                        break
                except httpx.HTTPError:
                    pass
                time.sleep(0.1)
            else:
                raise RuntimeError("测试服务启动超时")
            yield base, process
        finally:
            stop_process(process)


@pytest.fixture
def tls_files(tmp_path: Path) -> tuple[Path, Path]:
    """生成仅本轮有效的 localhost 测试证书，客户端仍做完整验证。"""
    openssl = os.getenv("OPENSSL_BINARY") or shutil.which("openssl")
    if not openssl:
        pytest.skip("需 OPENSSL_BINARY 或 PATH 中的 openssl")
    cert, key = tmp_path / "ca.pem", tmp_path / "key.pem"
    result = subprocess.run(
        [
            openssl,
            "req",
            "-x509",
            "-newkey",
            "rsa:2048",
            "-nodes",
            "-sha256",
            "-days",
            "1",
            "-keyout",
            str(key),
            "-out",
            str(cert),
            "-subj",
            "/CN=localhost",
            "-addext",
            "subjectAltName=DNS:localhost,IP:127.0.0.1",
        ],
        capture_output=True,
        timeout=15,
    )
    assert result.returncode == 0, "测试证书生成失败"
    return cert, key
