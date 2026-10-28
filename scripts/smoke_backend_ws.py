"""在临时数据库上启动真实后端，验证双客户端广播、拒绝握手和日志脱敏。"""

import json
import os
import secrets
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from urllib.parse import urlencode

import httpx
from websockets.exceptions import InvalidStatus
from websockets.sync.client import connect

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    """自动清理进程和临时数据，断言失败以非零状态退出。"""
    with tempfile.TemporaryDirectory(prefix="idp-ws-") as directory:
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            port = probe.getsockname()[1]
        token = secrets.token_urlsafe(32)
        environment = os.environ.copy()
        environment.update(API_TOKEN=token, DB_PATH=str(Path(directory) / "smoke.db"))
        with tempfile.TemporaryFile() as log:
            process = subprocess.Popen(
                [
                    sys.executable,
                    "-m",
                    "uvicorn",
                    "app.main:app",
                    "--host",
                    "127.0.0.1",
                    "--port",
                    str(port),
                    "--workers",
                    "1",
                    "--ws",
                    "websockets-sansio",
                    "--ws-max-size",
                    "4096",
                ],
                cwd=ROOT / "backend",
                env=environment,
                stdout=log,
                stderr=log,
            )
            try:
                base_url = f"http://127.0.0.1:{port}"
                with httpx.Client(base_url=base_url, timeout=5, trust_env=False) as client:
                    deadline = time.monotonic() + 15
                    while True:
                        try:
                            client.get("/api/health").raise_for_status()
                            break
                        except httpx.HTTPError:
                            if process.poll() is not None or time.monotonic() >= deadline:
                                raise RuntimeError("测试后端未就绪；检查依赖和可用端口") from None
                            time.sleep(0.05)
                    ws_url = f"ws://127.0.0.1:{port}/ws"
                    rejected = 0
                    for query in ("", "?token=invalid-smoke-value"):
                        try:
                            with connect(ws_url + query, open_timeout=5, proxy=None):
                                raise AssertionError("无效凭证握手成功")
                        except InvalidStatus as exc:
                            assert exc.response.status_code == 403
                            rejected += 1
                    url = ws_url + "?" + urlencode({"token": token})
                    event_ids = set()
                    with connect(url, open_timeout=5, close_timeout=2, proxy=None) as first:
                        with connect(url, open_timeout=5, close_timeout=2, proxy=None) as second:
                            for number in range(30):
                                response = client.post(
                                    "/api/tasks",
                                    json={"title": f"网络验收 {number}"},
                                    headers={"X-API-Key": token},
                                )
                                assert response.status_code == 201
                                one = json.loads(first.recv(timeout=5))
                                two = json.loads(second.recv(timeout=5))
                                assert one == two
                                assert one["type"] == "task.created"
                                assert one["data"]["id"] == response.json()["id"]
                                event_ids.add(one["event_id"])
                    assert len(event_ids) == 30
                    assert len(client.get("/api/tasks", headers={"X-API-Key": token}).json()) == 30
            finally:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)
            log.seek(0)
            logs = log.read().decode("utf-8", errors="replace")
            assert token not in logs
            assert "invalid-smoke-value" not in logs
            assert "[REDACTED]" in logs
            print(
                json.dumps(
                    {
                        "clients": 2,
                        "events_per_client": len(event_ids),
                        "matching_event_ids": 30,
                        "rejected_handshakes": rejected,
                        "rejection_http_status": 403,
                        "query_redacted": True,
                        "database": "temporary",
                        "transport": "real Uvicorn HTTP Upgrade",
                    },
                    ensure_ascii=False,
                )
            )


if __name__ == "__main__":
    main()
