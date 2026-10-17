"""真实桌宠提醒验收：批量绘制、重连/故障去重，可选真实语音。"""

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

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def run(args) -> dict:
    """仅修改本进程 Settings；数据库、凭证和应用历史均隔离。"""
    from PyQt6.QtCore import QEvent, QObject, Qt, QTimer
    from PyQt6.QtWidgets import QApplication

    from pet.config import Settings
    from pet.window import PetWindow

    with tempfile.TemporaryDirectory(prefix="idp-gui-acceptance-") as directory:
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            port = probe.getsockname()[1]
        token = secrets.token_urlsafe(32)
        environment = os.environ.copy()
        environment.update(
            API_TOKEN=token,
            DB_PATH=str(Path(directory) / "acceptance.db"),
            SCHEDULER_ENABLED="true",
            SCHEDULER_INTERVAL_SECONDS=str(args.interval),
        )
        server_code = (
            "import uvicorn; uvicorn.run('app.main:app',host='127.0.0.1',port=%d,ws='websockets-sansio')"
            % port
        )
        if args.fail_first_commit:
            environment.update(
                SCHEDULER_LEASE_SECONDS="3",
                SCHEDULER_SEND_TIMEOUT_SECONDS="1",
                DB_TIMEOUT_SECONDS="0.2",
            )
            server_code = (
                "from app import reminder_store\n"
                "original = reminder_store.finish\n"
                "failed = False\n"
                "def finish(*args):\n"
                " global failed\n"
                " if not failed:\n"
                "  failed = True\n"
                "  raise RuntimeError('acceptance: crash after send before commit')\n"
                " return original(*args)\n"
                "reminder_store.finish = finish\n"
            ) + server_code
        if args.reconnect:
            # 测试进程在首次真实广播后关闭连接；不改变业务发送或去重实现。
            server_code = (
                "from app.push_service import PushService\n"
                "broadcast = PushService.broadcast\n"
                "disconnected = False\n"
                "async def reconnect_once(self, event):\n"
                " global disconnected\n"
                " sent = await broadcast(self, event)\n"
                " if sent and not disconnected:\n"
                "  disconnected = True\n"
                "  for ws in tuple(self._connections):\n"
                "   await ws.close(code=1012)\n"
                " return sent\n"
                "PushService.broadcast = reconnect_once\n"
            ) + server_code
        with tempfile.TemporaryFile() as log:
            server = subprocess.Popen(
                [str(ROOT / "backend/.venv/Scripts/python.exe"), "-c", server_code],
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
                            if server.poll() is not None or time.monotonic() > deadline:
                                raise RuntimeError("Temporary backend did not start") from None
                            time.sleep(0.05)

                settings = Settings()
                settings.backend_url, settings.api_token = base_url, token
                settings.llm_api_key = ""
                settings.persist_history = False
                settings.history_path = Path(directory) / "history.json"
                settings.enable_voice = args.voice
                settings.health_enabled = False
                settings.frames = []
                settings.bubble_timeout_ms = 60000
                settings.pet_name = (
                    "B2 故障恢复验收（临时环境）"
                    if args.fail_first_commit
                    else "B2 提醒验收（临时环境）"
                )
                app = QApplication([])
                window = PetWindow(settings)
                # 截图工具不枚举 Qt Tool 窗口；只在验收进程改为普通顶层窗口。
                if args.capture_window:
                    window.setWindowFlag(Qt.WindowType.Tool, False)
                report = {
                    "head_sha": subprocess.check_output(
                        ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
                    ).strip(),
                    "interval_seconds": args.interval,
                    "lead_seconds": args.lead,
                    "fault_after_first_send": args.fail_first_commit,
                    "voice_enabled": args.voice,
                    "reconnect": args.reconnect,
                    "samples": args.samples,
                    "capture_window": args.capture_window,
                    "measurement": "real WsListener -> PetWindow -> REST -> bubble paint callback",
                    "events": [],
                    "paints": [],
                    "notifications": [],
                    "voice_requests": [],
                    "playback_states": [],
                    "media_status": [],
                    "errors": [],
                    "rows": [],
                }

                def save():
                    args.output.parent.mkdir(parents=True, exist_ok=True)
                    args.output.write_text(
                        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
                    )

                def received(event):
                    if event.get("type") != "reminder.due":
                        return
                    report["events"].append(
                        {
                            "event_id": event["event_id"],
                            "id": event["data"]["id"],
                            "handled_epoch": time.time(),
                        }
                    )
                    save()

                remind = window._remind_health
                speak = window._speak

                def observe_notification(text):
                    report["notifications"].append({"text": text, "epoch": time.time()})
                    remind(text)
                    save()

                def observe_voice(text):
                    report["voice_requests"].append({"text": text, "epoch": time.time()})
                    speak(text)
                    window.tts_worker.error.connect(
                        lambda error: record("errors", "tts:" + type(error).__name__)
                    )

                def record(key, value):
                    report[key].append({"value": str(value), "epoch": time.time()})
                    save()

                # 仅旁路记录，调用真实业务方法；不替换合成器或播放器。
                window._remind_health = observe_notification
                window._speak = observe_voice
                window.player.playbackStateChanged.connect(
                    lambda state: record("playback_states", state.name)
                )
                window.player.mediaStatusChanged.connect(
                    lambda status: record("media_status", status.name)
                )
                window.player.errorOccurred.connect(lambda error: record("errors", error.name))

                class PaintObserver(QObject):
                    def eventFilter(self, obj, event):  # noqa: N802
                        if event.type() == QEvent.Type.Paint:
                            text = window.bubble._text
                            QTimer.singleShot(0, lambda: painted(text))
                        return False

                def painted(text):
                    row = next((r for r in report["rows"] if r["expected_text"] == text), None)
                    if row is None or row.get("painted_epoch"):
                        return
                    now = time.time()
                    row["painted_epoch"] = now
                    report["paints"].append(
                        {
                            "reminder_id": row["id"],
                            "painted_epoch": now,
                            "from_created_seconds": now - row["created_epoch"],
                            "from_due_seconds": now - row["due_epoch"],
                            "visible": window.bubble.isVisible(),
                            "text": text,
                        }
                    )
                    save()

                def create():
                    created = time.time()
                    for number in range(args.samples):
                        due = created + args.lead + number * args.spacing
                        title = f"B2 验收提醒 {number + 1}"
                        body = "请确认桌宠已显示到期提醒"
                        item = window.backend.create_reminder(
                            title,
                            datetime.fromtimestamp(due, timezone.utc).isoformat(),
                            body=body,
                            channel="pc",
                        )
                        report["rows"].append(
                            {
                                "id": item["id"],
                                "created_epoch": created,
                                "due_epoch": due,
                                "expected_text": f"⏰ {title} {body}",
                            }
                        )
                    save()

                def finish():
                    report["reminders"] = window.backend.list_reminders()
                    report["duplicate_events"] = len(report["events"]) - len(
                        {event["event_id"] for event in report["events"]}
                    )
                    delays = sorted(p["from_due_seconds"] for p in report["paints"])
                    report["summary"] = {
                        "received": len({e["id"] for e in report["events"]}),
                        "displayed": len(delays),
                        "notifications": len(report["notifications"]),
                        "duplicates_suppressed": len(report["events"])
                        - len(report["notifications"]),
                        "done": sum(r["done"] for r in report["reminders"]),
                        "within_limit": sum(0 <= d <= args.max_delay for d in delays),
                        "max_delay_seconds": args.max_delay,
                        "p50_seconds": delays[math.ceil(len(delays) * 0.50) - 1]
                        if delays
                        else None,
                        "p95_seconds": delays[math.ceil(len(delays) * 0.95) - 1]
                        if delays
                        else None,
                        "max_seconds": max(delays, default=None),
                    }
                    report["completed"] = True
                    save()
                    if window.tts_worker is not None and window.tts_worker.isRunning():
                        # 只在测试收尾等待有超时的合成请求，避免销毁运行中的 QThread。
                        window.tts_worker.wait(75000)
                    window.player.stop()
                    window.close()
                    app.quit()

                observer = PaintObserver(window)
                window.bubble.installEventFilter(observer)
                window.ws.event.connect(received)
                window.show()
                QTimer.singleShot(2000, create)
                duration = (
                    2 + args.lead + (args.samples - 1) * args.spacing + args.interval + args.hold
                )
                QTimer.singleShot(int(duration * 1000), finish)
                app.exec()
            finally:
                server.terminate()
                try:
                    server.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    server.kill()
                    server.wait(timeout=5)
            log.seek(0)
            assert token not in log.read().decode("utf-8", errors="replace")
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--interval", type=float, default=1)
    parser.add_argument("--lead", type=float, default=10)
    parser.add_argument("--hold", type=float, default=20)
    parser.add_argument("--fail-first-commit", action="store_true")
    parser.add_argument("--capture-window", action="store_true")
    parser.add_argument("--reconnect", action="store_true")
    parser.add_argument("--voice", action="store_true")
    parser.add_argument("--samples", type=int, default=1)
    parser.add_argument("--spacing", type=float, default=2)
    parser.add_argument("--max-delay", type=float, default=5)
    parser.add_argument("--output", type=Path, required=True)
    options = parser.parse_args()
    seconds = (options.interval, options.lead, options.hold, options.spacing, options.max_delay)
    if not all(math.isfinite(n) and n > 0 for n in seconds) or options.hold < 5:
        parser.error("seconds must be positive finite values; hold must be at least five seconds")
    if not 1 <= options.samples <= 100 or (options.voice and options.samples != 1):
        parser.error("samples must be 1..100; real voice acceptance uses one sample")
    result = run(options)
    summary = result["summary"]
    assert summary["displayed"] == summary["notifications"] == summary["done"] == options.samples
    assert summary["within_limit"] == options.samples
    if options.fail_first_commit:
        assert result["duplicate_events"] >= 1 and summary["duplicates_suppressed"] >= 1
    if options.voice:
        assert len(result["voice_requests"]) == 1
        assert any(s["value"] == "PlayingState" for s in result["playback_states"])
        assert any(s["value"] == "EndOfMedia" for s in result["media_status"])
        assert not result["errors"]
