"""真实 HTTP/WS 双用户隔离；临时库，微信登录仅用本地替身。"""

import json
import os
import secrets
import socket
import subprocess
import sys
import time
from pathlib import Path

import httpx
from check_c3_integration import temporary_test_dir
from websockets.sync.client import connect


def main():
    root = Path(__file__).resolve().parents[1]
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    with temporary_test_dir() as directory:
        env = os.environ.copy()
        env.update(
            PYTHONPATH=str(root / "backend"),
            DB_PATH=str(Path(directory) / "test.db"),
            API_TOKEN=secrets.token_hex(24),
            WX_ENABLED="true",
            WX_APPID="b8-test",
            WX_SECRET=secrets.token_hex(24),
            WX_TEMPLATE_ID="test",
            SCHEDULER_ENABLED="false",
            ALLOW_LEGACY_API_KEY="false",  # pragma: allowlist secret -- boolean switch
            C3_TEST_PORT=str(port),
        )
        with (Path(directory) / "server.log").open("w", encoding="utf-8") as log:
            proc = subprocess.Popen(
                [sys.executable, str(root / "scripts/c3_test_server.py")],
                env=env,
                stdout=log,
                stderr=log,
                cwd=root,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
            )
            try:
                with httpx.Client(
                    base_url=f"http://127.0.0.1:{port}", trust_env=False, timeout=5
                ) as c:
                    for _ in range(100):
                        try:
                            if c.get("/api/health").status_code == 200:
                                break
                        except httpx.HTTPError:
                            pass
                        if proc.poll() is not None:
                            raise RuntimeError("test server exited")
                        time.sleep(0.1)
                    else:
                        raise RuntimeError("test server timeout")
                    users = [
                        c.post("/api/wechat/login", json={"code": name}).json()
                        for name in ("alice", "bob")
                    ]
                    headers = [{"Authorization": "Bearer " + u["session_token"]} for u in users]
                    assert c.get("/api/tasks").status_code == 401
                    assert (
                        c.get("/api/tasks", headers={"X-API-Key": env["API_TOKEN"]}).status_code
                        == 401
                    )
                    code = c.post("/api/auth/pairing", headers=headers[0]).json()["pairing_code"]
                    device = c.post("/api/auth/device", json={"pairing_code": code}).json()
                    assert device["user_id"] == users[0]["account_id"]
                    assert (
                        c.post("/api/auth/device", json={"pairing_code": code}).status_code == 401
                    )
                    with (
                        connect(f"ws://127.0.0.1:{port}/ws?token={device['device_token']}") as wa,
                        connect(
                            f"ws://127.0.0.1:{port}/ws?token={users[1]['session_token']}"
                        ) as wb,
                    ):
                        rows = [
                            c.post(
                                "/api/tasks",
                                headers=h,
                                json={"title": "private", "remind_at": "2040-01-01T08:00:00+08:00"},
                            ).json()
                            for h in headers
                        ]
                        assert json.loads(wa.recv(timeout=2))["data"]["id"] == rows[0]["id"]
                        assert json.loads(wb.recv(timeout=2))["data"]["id"] == rows[1]["id"]
                        for ws in (wa, wb):
                            try:
                                ws.recv(timeout=0.2)
                            except TimeoutError:
                                pass
                            else:
                                raise AssertionError("cross-user event")
                        for index, h in enumerate(headers):
                            other = rows[1 - index]["id"]
                            assert c.get(f"/api/tasks/{other}", headers=h).status_code == 404
                            assert (
                                c.put(
                                    f"/api/tasks/{other}", headers=h, json={"done": True}
                                ).status_code
                                == 404
                            )
                            assert c.delete(f"/api/tasks/{other}", headers=h).status_code == 404
                            assert len(c.get("/api/tasks", headers=h).json()) == 1
                            assert len(c.get("/api/reminders", headers=h).json()) == 1
                    hd = {"Authorization": "Bearer " + device["device_token"]}
                    assert c.post("/api/auth/logout", headers=hd).status_code == 204
                    assert c.get("/api/tasks", headers=hd).status_code == 401
                    print(
                        json.dumps(
                            {
                                "passed": True,
                                "users": 2,
                                "http_isolation": True,
                                "ws_isolation": True,
                                "pairing_single_use": True,
                                "revocation": True,
                                "external_requests": 0,
                            }
                        )
                    )
            finally:
                proc.terminate()
                try:
                    proc.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait(timeout=5)


if __name__ == "__main__":
    main()
