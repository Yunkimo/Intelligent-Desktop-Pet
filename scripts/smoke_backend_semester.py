"""用临时库和真实 HTTP/WS 验证 B6 双端同步、断线补读及重启持久化。"""

import json
import os
import secrets
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import httpx
from websockets.sync.client import connect

ROOT = Path(__file__).resolve().parents[1]


def stop(process):
    """只停止本脚本创建的进程树，兼容 Windows 虚拟环境启动器。"""
    if process.poll() is not None:
        return
    if os.name == "nt":
        subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"], capture_output=True)
    else:
        process.terminate()
    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)


def main():
    with tempfile.TemporaryDirectory(prefix="b6-smoke-") as directory:
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            port = probe.getsockname()[1]
        token = secrets.token_urlsafe(32)
        env = dict(
            os.environ,
            API_TOKEN=token,
            DB_PATH=str(Path(directory) / "test.db"),
            SCHEDULER_ENABLED="false",
            WX_ENABLED="false",
            LLM_API_KEY="",
            PYTHONUTF8="1",
        )
        base = f"http://127.0.0.1:{port}"
        url = f"ws://127.0.0.1:{port}/ws?token={token}"
        count = 0
        with tempfile.TemporaryFile() as log:

            def start():
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
                        "--no-access-log",
                    ],
                    cwd=ROOT / "backend",
                    env=env,
                    stdout=log,
                    stderr=log,
                    creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
                )
                try:
                    with httpx.Client(base_url=base, trust_env=False, timeout=1) as health:
                        for _ in range(100):
                            try:
                                if health.get("/api/health").status_code == 200:
                                    return process
                            except httpx.HTTPError:
                                pass
                            time.sleep(0.1)
                    raise RuntimeError("B6 isolated backend not ready")
                except BaseException:
                    stop(process)
                    raise

            process = start()
            try:
                with httpx.Client(
                    base_url=base, headers={"X-API-Key": token}, trust_env=False, timeout=5
                ) as api:

                    def call(method, path, body=None):
                        response = api.request(method, path, json=body)
                        response.raise_for_status()
                        return response.json() if response.content else None

                    with (
                        connect(url, proxy=None, close_timeout=2) as first,
                        connect(url, proxy=None, close_timeout=2) as second,
                    ):

                        def receive(kind):
                            nonlocal count
                            one = json.loads(first.recv(timeout=5))
                            assert one == json.loads(second.recv(timeout=5))
                            assert one["type"] == kind
                            count += 1

                        settings = call(
                            "PUT", "/api/semester", {"start_date": "2026-09-07", "total_weeks": 18}
                        )
                        receive("semester.updated")
                        result = call("GET", "/api/calendar?date=2026-10-30")
                        assert (result["week"], result["day_of_week"]) == (8, 5)
                        payload = {
                            "courses": [
                                {
                                    "name": f"B6-{n}",
                                    "day_of_week": 5,
                                    "start_time": "08:00",
                                    "end_time": "09:00",
                                    "weeks": [8],
                                }
                                for n in range(5)
                            ]
                        }
                        created = call("POST", "/api/courses/bulk", payload)["created"]
                        receive("course.created")
                        for ws in (first, second):
                            try:
                                ws.recv(timeout=0.2)
                                raise AssertionError("batch emitted extra notification")
                            except TimeoutError:
                                pass
                        assert len(call("GET", "/api/calendar?date=2026-10-30")["courses"]) == 5
                        cid = created[0]["id"]
                        call("PUT", f"/api/courses/{cid}", {"weeks": [7]})
                        receive("course.updated")
                        assert len(call("GET", "/api/calendar?date=2026-10-30")["courses"]) == 4
                        call("DELETE", f"/api/courses/{cid}")
                        receive("course.deleted")
                        task = call("POST", "/api/tasks", {"title": "B6-network"})
                        receive("task.created")
                        call("PUT", f"/api/tasks/{task['id']}", {"done": True})
                        receive("task.updated")
                        call("DELETE", f"/api/tasks/{task['id']}")
                        receive("task.deleted")
                        assert api.delete("/api/tasks/999999").status_code == 404
                        assert (
                            api.put("/api/semester", json={"start_date": "invalid"}).status_code
                            == 422
                        )
                        for ws in (first, second):
                            try:
                                ws.recv(timeout=0.2)
                                raise AssertionError("failed request emitted event")
                            except TimeoutError:
                                pass
                    # 断线期间写入，不要求历史消息补发；重连后读快照。
                    missed = call("POST", "/api/tasks", {"title": "offline-change"})
                    with connect(url, proxy=None, close_timeout=2):
                        assert missed in call("GET", "/api/tasks")
                stop(process)
                process = start()
                with httpx.Client(
                    base_url=base, headers={"X-API-Key": token}, trust_env=False, timeout=5
                ) as api:
                    assert api.get("/api/semester").json() == settings
                    assert len(api.get("/api/calendar?date=2026-10-30").json()["courses"]) == 4
            finally:
                stop(process)
        print(
            json.dumps(
                {
                    "passed": True,
                    "matching_events_per_client": count,
                    "batch_refresh_events": 1,
                    "reconnect_rest_recovery": True,
                    "restart_persistence": True,
                    "production_accessed": False,
                    "transport": "real HTTP and WebSocket",
                }
            )
        )


if __name__ == "__main__":
    main()
