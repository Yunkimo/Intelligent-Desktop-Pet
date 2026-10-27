"""测量云端提醒到真实可见气泡绘制的延迟；只清理本轮唯一标记记录。"""

import argparse
import json
import logging
import math
import os
import re
import secrets
import sys
import tempfile
import time
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def clock_bounds(client):
    """HTTP Date 为整秒，按往返区间保守约束服务器时钟减本机时钟。"""
    probes = []
    for _ in range(8):
        start = time.time()
        response = client.get("/api/health", headers={"Cache-Control": "no-cache"})
        end = time.time()
        response.raise_for_status()
        if response.json() != {"status": "ok"} or "age" in response.headers:
            raise ValueError("Unusable health clock response")
        server = parsedate_to_datetime(response.headers["date"]).timestamp()
        probes.append(
            {
                "start": start,
                "end": end,
                "date_epoch": server,
                "lower": server - end,
                "upper": server + 1 - start,
            }
        )
        time.sleep(0.17)
    lower = max(p["lower"] for p in probes)
    upper = min(p["upper"] for p in probes)
    if lower > upper or upper - lower > 1.5:
        raise ValueError("Clock bounds inconsistent or too uncertain")
    return {"lower_seconds": lower, "upper_seconds": upper, "probes": probes}


def run(args):
    from PyQt6.QtCore import QEvent, QObject, QTimer
    from PyQt6.QtWidgets import QApplication

    from pet.config import Settings
    from pet.window import PetWindow

    if args.output.exists():
        raise FileExistsError("Output exists; inspect prior run instead of repeating POST")
    source = args.config.read_text(encoding="utf-8-sig")
    match = re.search(r"apiKey\s*:\s*(['\"])([^'\"]*)\1", source)
    if not match or not match.group(2).strip():
        raise ValueError("Missing private connection key")
    token = match.group(2)
    # Disable library debug logging; exception output below never includes requests or tokens.
    logging.disable(logging.CRITICAL)
    for key in list(os.environ):
        if key.upper() in {"HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "QT_QPA_PLATFORM"}:
            del os.environ[key]
    os.environ["LLM_API_KEY"] = ""
    report = {
        "run_id": secrets.token_hex(6),
        "base_url": args.base_url,
        "samples": args.samples,
        "limit_seconds": 5,
        "rows": [],
        "errors": [],
        "measurement": "real WsListener -> PetWindow REST reconciliation -> visible bubble Paint callback",
        "voice_measured": False,
        "completed": False,
        "cleanup_confirmed": False,
        "clock_assumption": "Nginx HTTP Date and backend scheduler use the same host clock; no clock step during run",
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)

    def save():
        args.output.write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )

    save()
    started_wall, started_mono = time.time(), time.monotonic()
    with (
        httpx.Client(
            base_url=args.base_url, headers={"X-API-Key": token}, timeout=7, trust_env=False
        ) as client,
        tempfile.TemporaryDirectory(prefix="c4-latency-ui-") as temporary,
    ):
        report["clock_before"] = clock_bounds(client)
        settings = Settings()
        settings.backend_url, settings.api_token = args.base_url, token
        settings.llm_api_key = ""
        settings.persist_history = False
        settings.history_path = Path(temporary) / "history.json"
        settings.usage_path = Path(temporary) / "usage.json"
        settings.agent_status_path = Path(temporary) / "agent-status.json"
        settings.enable_voice = settings.health_enabled = False
        settings.monitor_claude = settings.monitor_codex = settings.tray_enabled = False
        settings.frames = []
        settings.pet_name = "C4 云端时延测试"
        settings.bubble_timeout_ms = 6000
        app = QApplication([])
        if app.platformName().lower() in {"offscreen", "minimal"}:
            raise ValueError("Actual desktop platform required")
        report["qt_platform"] = app.platformName()
        window = PetWindow(settings)
        if window.hotkey is not None:
            window.hotkey.stop()
        window.ws.error.disconnect()
        window.ws.error.connect(lambda _: report["errors"].append("websocket_error"))
        original_notification = window._remind_health

        def notification(text):
            for row in report["rows"]:
                if row["title"] in text:
                    row["notifications"] = row.get("notifications", 0) + 1
            original_notification(text)

        window._remind_health = notification

        def received(event):
            if event.get("type") == "reminder.due":
                for row in report["rows"]:
                    if row.get("id") == event.get("data", {}).get("id"):
                        row.setdefault("events", []).append(
                            {"event_id": event.get("event_id"), "epoch": time.time()}
                        )

        def painted(text):
            for row in report["rows"]:
                if row["expected_text"] == text and not row.get("painted_epoch"):
                    row.update(
                        painted_epoch=time.time(),
                        visible=window.bubble.isVisible(),
                        notifications=row.get("notifications", 0),
                    )
                    # Only the test bubble is captured, never the user's desktop.
                    image = args.output.with_name(
                        args.output.stem + "-" + str(row["number"]) + ".png"
                    )
                    row["bubble_capture"] = image.name
                    row["capture_saved"] = window.bubble.grab().save(str(image))
                    save()

        class Observer(QObject):
            def eventFilter(self, obj, event):  # noqa: N802
                if event.type() == QEvent.Type.Paint:
                    text = window.bubble._text
                    QTimer.singleShot(0, lambda: painted(text))
                return False

        observer = Observer(window)
        window.bubble.installEventFilter(observer)
        window.ws.event.connect(received)

        def create():
            try:
                clock = report["clock_before"]
                midpoint = (clock["lower_seconds"] + clock["upper_seconds"]) / 2
                first_due = time.time() + midpoint + 15
                for number in range(args.samples):
                    due = first_due + number * 8.37
                    title = "C4-latency-" + report["run_id"] + "-" + str(number + 1)
                    body = "C4 到期展示时延核验"
                    row = {
                        "number": number + 1,
                        "title": title,
                        "body": body,
                        "due_epoch": due,
                        "due_at": datetime.fromtimestamp(due, timezone.utc).isoformat(),
                        "expected_text": "⏰ " + title + " " + body,
                        "create_attempted": True,
                    }
                    report["rows"].append(row)
                    save()  # Ownership marker survives an ambiguous POST result; never retry.
                    response = client.post(
                        "/api/reminders",
                        json={
                            "title": title,
                            "body": body,
                            "remind_at": row["due_at"],
                            "channel": "pc",
                        },
                    )
                    response.raise_for_status()
                    created = response.json()
                    if (
                        response.status_code != 201
                        or created.get("title") != title
                        or type(created.get("id")) is not int
                    ):
                        raise ValueError("Unconfirmed reminder creation")
                    row["id"] = created["id"]
                    save()
                print(
                    json.dumps({"prepared": len(report["rows"]), "run_id": report["run_id"]}),
                    flush=True,
                )
            except Exception as exc:
                report["errors"].append("create:" + type(exc).__name__)
                save()
                app.quit()

        def finish():
            report["completed"] = True
            app.quit()

        window.show()
        window.move(80, 250)
        QTimer.singleShot(4000, create)
        QTimer.singleShot(int((4 + 15 + (args.samples - 1) * 8.37 + 14) * 1000), finish)
        try:
            app.exec()
            report["clock_after"] = clock_bounds(client)
        finally:
            window._quit()
            # Inspect only own exact title/body/channel markers; never delete a modified record.
            response = client.get("/api/reminders")
            response.raise_for_status()
            all_rows = response.json()
            for row in report["rows"]:
                matches = [r for r in all_rows if r.get("title") == row["title"]]
                for remote in matches:
                    if (
                        remote.get("body") != row["body"]
                        or remote.get("channel") != "pc"
                        or row.get("id", remote["id"]) != remote["id"]
                    ):
                        raise ValueError("Owned marker changed; preserve record")
                    row["id"] = remote["id"]
                    row["done"] = remote.get("done") in (True, 1)
                    delivery = client.get("/api/reminders/" + str(remote["id"]) + "/delivery")
                    delivery.raise_for_status()
                    row["delivery"] = {
                        k: delivery.json().get(k) for k in ("status", "attempts", "event_id")
                    }
                    deleted = client.delete("/api/reminders/" + str(remote["id"]))
                    if deleted.status_code != 204:
                        raise ValueError("Cleanup not confirmed")
            response = client.get("/api/reminders")
            response.raise_for_status()
            own_titles = {r["title"] for r in report["rows"]}
            report["cleanup_confirmed"] = not any(
                r.get("title") in own_titles for r in response.json()
            )
            save()
        drift = (time.time() - started_wall) - (time.monotonic() - started_mono)
        report["local_clock_step_seconds"] = drift
        before, after = report["clock_before"], report["clock_after"]
        # Use the union, not intersection, across start/end to allow measured clock drift.
        lower = min(before["lower_seconds"], after["lower_seconds"])
        upper = max(before["upper_seconds"], after["upper_seconds"])
        for row in report["rows"]:
            if row.get("painted_epoch"):
                raw = row["painted_epoch"] - row["due_epoch"]
                row["delay_lower_seconds"] = raw + lower
                row["delay_upper_seconds"] = raw + upper
            row["passed"] = bool(
                row.get("visible")
                and row.get("capture_saved")
                and row.get("notifications") == 1
                and len(row.get("events", [])) == 1
                and row.get("done")
                and row.get("delivery", {}).get("status") == "sent"
                and row.get("delivery", {}).get("attempts") == 1
                and 0 <= row.get("delay_lower_seconds", -1)
                and row.get("delay_upper_seconds", math.inf) <= 5
            )
        report["passed"] = bool(
            report["completed"]
            and len(report["rows"]) == args.samples
            and report["cleanup_confirmed"]
            and not report["errors"]
            and abs(drift) < 0.1
            and all(r["passed"] for r in report["rows"])
        )
        save()
        print(
            json.dumps(
                {
                    "passed": report["passed"],
                    "samples": len(report["rows"]),
                    "cleanup_confirmed": report["cleanup_confirmed"],
                    "delay_upper_seconds": [r.get("delay_upper_seconds") for r in report["rows"]],
                }
            )
        )
        return report["passed"]


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", required=True)
    parser.add_argument(
        "--config", type=Path, required=True, help="本机忽略的 miniprogram/config.js，凭据不输出"
    )
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--samples", type=int, default=5, choices=range(1, 11))
    options = parser.parse_args()
    try:
        raise SystemExit(0 if run(options) else 1)
    except Exception as error:
        print(
            json.dumps(
                {
                    "failed": True,
                    "error_type": type(error).__name__,
                    "note": "Inspect saved markers and clean up before retrying; never repeat an ambiguous POST.",
                }
            )
        )
        raise SystemExit(1)
