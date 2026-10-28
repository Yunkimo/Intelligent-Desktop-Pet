"""启动临时后端，按计划到期到 WS 收包测量提醒延迟，不代表 GUI 展示。"""

import argparse
import json
import math
import os
import secrets
import socket
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlencode

import httpx
from websockets.sync.client import connect

ROOT = Path(__file__).resolve().parents[1]


def iso(timestamp: float) -> str:
    """格式化 UTC 证据时间。"""
    return datetime.fromtimestamp(timestamp, timezone.utc).isoformat(timespec="microseconds")


def run(interval: float, samples: int, max_delay: float) -> dict:
    """以独立进程与临时库验证；所有等待有上限，始终清理进程。"""
    with tempfile.TemporaryDirectory(prefix="idp-scheduler-") as directory:
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            port = probe.getsockname()[1]
        token = secrets.token_urlsafe(32)
        environment = os.environ.copy()
        environment.update(
            API_TOKEN=token,
            DB_PATH=str(Path(directory) / "reminders.db"),
            SCHEDULER_ENABLED="true",
            SCHEDULER_INTERVAL_SECONDS=str(interval),
        )
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
                ],
                cwd=ROOT / "backend",
                env=environment,
                stdout=log,
                stderr=log,
            )
            try:
                with httpx.Client(
                    base_url=f"http://127.0.0.1:{port}",
                    timeout=5,
                    trust_env=False,
                    headers={"X-API-Key": token},
                ) as client:
                    deadline = time.monotonic() + 15
                    while True:
                        try:
                            client.get("/api/health").raise_for_status()
                            break
                        except httpx.HTTPError:
                            if process.poll() is not None or time.monotonic() >= deadline:
                                raise RuntimeError("临时后端未就绪") from None
                            time.sleep(0.05)
                    url = f"ws://127.0.0.1:{port}/ws?" + urlencode({"token": token})
                    rows = {}
                    duplicate_count = 0
                    wall_start, mono_start = time.time(), time.monotonic()
                    with connect(url, open_timeout=5, close_timeout=2, proxy=None) as websocket:
                        start = time.time() + 0.5
                        for number in range(samples):
                            due = start + interval * number / samples
                            response = client.post(
                                "/api/reminders",
                                json={
                                    "title": f"B2 latency sample {number}",
                                    "remind_at": iso(due),
                                    "channel": "pc",
                                },
                            )
                            response.raise_for_status()
                            rows[response.json()["id"]] = {
                                "reminder_id": response.json()["id"],
                                "due_at_utc": iso(due),
                                "due_epoch": due,
                                "event_id": None,
                                "received_at_utc": None,
                                "latency_ms": None,
                                "done": False,
                            }
                        deadline = time.monotonic() + 2 * interval + max_delay + 5
                        received = 0
                        while received < samples and time.monotonic() < deadline:
                            try:
                                message = websocket.recv(
                                    timeout=max(0.01, deadline - time.monotonic())
                                )
                            except TimeoutError:
                                break
                            arrived = time.time()
                            event = json.loads(message)
                            assert event["type"] == "reminder.due"
                            row = rows[event["data"]["id"]]
                            if row["event_id"] is not None:
                                duplicate_count += 1
                                continue
                            row.update(
                                event_id=event["event_id"],
                                received_at_utc=iso(arrived),
                                latency_ms=round((arrived - row["due_epoch"]) * 1000, 3),
                            )
                            received += 1
                        deadline = time.monotonic() + 5
                        while True:
                            states = {
                                row["id"]: row["done"]
                                for row in client.get("/api/reminders").json()
                            }
                            if all(states.get(key) for key in rows) or time.monotonic() >= deadline:
                                break
                            time.sleep(0.01)
                        for key, row in rows.items():
                            row["done"] = bool(states.get(key))
                            row.pop("due_epoch")
                    clock_drift_ms = (
                        abs((time.time() - wall_start) - (time.monotonic() - mono_start)) * 1000
                    )
            finally:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)
            log.seek(0)
            assert token not in log.read().decode("utf-8", errors="replace")
    delays = sorted(row["latency_ms"] for row in rows.values() if row["latency_ms"] is not None)
    within_limit = sum(0 <= delay <= max_delay * 1000 for delay in delays)
    return {
        "interval_seconds": interval,
        "samples": samples,
        "received": len(delays),
        "timeouts": samples - len(delays),
        "duplicates": duplicate_count,
        "receive_success_rate": len(delays) / samples,
        "max_delay_seconds": max_delay,
        "within_limit": within_limit,
        "done_count": sum(row["done"] for row in rows.values()),
        "p50_ms": delays[math.ceil(len(delays) * 0.5) - 1] if delays else None,
        "p95_ms": delays[math.ceil(len(delays) * 0.95) - 1] if delays else None,
        "max_ms": max(delays) if delays else None,
        "clock_drift_ms": round(clock_drift_ms, 3),
        "measurement": "scheduled UTC due time to local WebSocket receive; not GUI display",
        "rows": list(rows.values()),
    }


def main() -> None:
    """输出原始数据；超时、提前触发、重复或状态错误均返回非零。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--interval", type=float, default=1)
    parser.add_argument("--samples", type=int, default=30)
    parser.add_argument("--max-delay", type=float, default=None)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    limit = args.max_delay if args.max_delay is not None else args.interval + 5
    if not all(math.isfinite(n) and n > 0 for n in (args.interval, limit)) or args.samples < 1:
        parser.error("间隔和延迟必须为正有限数，样本数至少 1")
    result = run(args.interval, args.samples, limit)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
    print(json.dumps({key: value for key, value in result.items() if key != "rows"}))
    assert result["within_limit"] == args.samples and result["done_count"] == args.samples
    assert result["duplicates"] == 0


if __name__ == "__main__":
    main()
