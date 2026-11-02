"""A19 真实 HTTP/WS 验证；微信上游仅本地替身，隔离数据库。"""

import argparse
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
from contextlib import closing
from pathlib import Path

import httpx
import websocket

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from pet.backend_client import BackendClient, SessionExpired, build_ws_url  # noqa: E402


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--backend-python", default=sys.executable)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    with tempfile.TemporaryDirectory(prefix="a19-check-") as directory:
        env = {
            **os.environ,
            "PYTHONPATH": str(root / "backend"),
            "DB_PATH": str(Path(directory) / "test.db"),
            "API_TOKEN": "a19-local-test",
            "ALLOW_LEGACY_API_KEY": "false",  # pragma: allowlist secret -- boolean switch
            "WX_ENABLED": "true",
            "WX_APPID": "a19-test",
            "WX_SECRET": "test-placeholder",  # pragma: allowlist secret -- local mock only
            "WX_TEMPLATE_ID": "test",
            "SCHEDULER_ENABLED": "false",
            "C3_TEST_PORT": str(port),
        }
        with tempfile.TemporaryFile() as log:
            proc = subprocess.Popen(
                [args.backend_python, str(root / "scripts/c3_test_server.py")],
                env=env,
                stdout=log,
                stderr=log,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
            )
            try:
                base = f"http://127.0.0.1:{port}"
                with httpx.Client(trust_env=False, timeout=5) as http:
                    for _ in range(100):
                        try:
                            if http.get(base + "/api/health").status_code == 200:
                                break
                        except httpx.HTTPError:
                            pass
                        time.sleep(0.1)
                    else:
                        raise RuntimeError("test backend did not start")
                    clients = []
                    for name in ("a", "b"):
                        identity = http.post(base + "/api/wechat/login", json={"code": name}).json()
                        pair = http.post(
                            base + "/api/auth/pairing",
                            headers={"Authorization": "Bearer " + identity["session_token"]},
                        ).json()
                        client = BackendClient(base, "a19-local-test")
                        result = client.device_login(pair["pairing_code"])
                        client.session_token = result["device_token"]
                        clients.append(client)
                    a, b = clients
                    with (
                        closing(
                            websocket.create_connection(
                                build_ws_url(base, a.session_token), timeout=2
                            )
                        ) as wa,
                        closing(
                            websocket.create_connection(
                                build_ws_url(base, b.session_token), timeout=2
                            )
                        ) as wb,
                    ):
                        ta = a.create_task("A-private")
                        tb = b.create_task("B-private")
                        assert json.loads(wa.recv())["data"]["id"] == ta["id"]
                        assert json.loads(wb.recv())["data"]["id"] == tb["id"]
                        assert [t["id"] for t in a.list_tasks()] == [ta["id"]]
                        assert [t["id"] for t in b.list_tasks()] == [tb["id"]]
                        a.session_token = b.session_token
                        assert a.list_tasks() == b.list_tasks()
                    b.logout()
                    try:
                        b.list_tasks()
                    except SessionExpired:
                        pass
                    else:
                        raise AssertionError("revoked session accepted")
                    print(
                        json.dumps(
                            {
                                "passed": True,
                                "desktop_client": True,
                                "two_users": True,
                                "ws_isolation": True,
                                "switch_account": True,
                                "revocation": True,
                                "production_accessed": False,
                            }
                        )
                    )
            finally:
                proc.terminate()
                try:
                    proc.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait()


if __name__ == "__main__":
    main()
