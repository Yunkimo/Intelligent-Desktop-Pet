"""天气提示：每晚到点查一次次日是否有雨，有雨时提醒带伞。

分两层：WeatherTipMonitor 只负责「到点触发一次」（同一天不重复），真正的
网络查询在 WeatherTipWorker(QThread) 里做，不阻塞 UI；有雨时发 tip 信号，
窗口据此弹气泡并按语音开关决定是否播报。网络失败/未绑定账号静默跳过，不刷屏。
"""

import json
import os
from datetime import datetime
from pathlib import Path

from PyQt6.QtCore import QObject, QThread, QTimer, pyqtSignal

from .backend_client import BackendClient

_CHECK_INTERVAL_MS = 60_000  # 每分钟对一次时间


class WeatherTipMonitor(QObject):
    """到点发一次 check_due；同一天只发一次，重启后仍不重复，跨天自动复位。"""

    check_due = pyqtSignal()

    def __init__(self, hour: int, state_path=None, clock=None, parent=None) -> None:
        super().__init__(parent)
        self._hour = hour
        self._clock = clock or datetime.now
        self._state_path = state_path
        self._fired_date = self._load_fired_date()
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._check)

    def start(self) -> None:
        self._timer.start(_CHECK_INTERVAL_MS)

    def stop(self) -> None:
        self._timer.stop()

    def _check(self) -> None:
        now = self._clock()
        if now.hour < self._hour:
            return
        key = now.date().isoformat()
        if self._fired_date == key:
            return
        self._fired_date = key
        self._save_fired_date(key)
        self.check_due.emit()

    def _load_fired_date(self) -> str | None:
        """读上次触发的日期；文件缺失或损坏按未触发处理。"""
        if self._state_path is None:
            return None
        try:
            data = json.loads(Path(self._state_path).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        value = data.get("last_fired_date") if isinstance(data, dict) else None
        return str(value) if isinstance(value, str) and value else None

    def _save_fired_date(self, value: str) -> None:
        if self._state_path is None:
            return
        path = Path(self._state_path)
        tmp = path.with_suffix(path.suffix + ".tmp")
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp.write_text(json.dumps({"last_fired_date": value}), encoding="utf-8")
            os.replace(tmp, path)
        except OSError:
            pass  # 写不进去也不影响本次提醒


class WeatherTipWorker(QThread):
    """后台查次日天气；只有「有雨且带提示文案」才发 tip，其余情况一律静默。"""

    tip = pyqtSignal(str)
    failed = pyqtSignal(str)

    def __init__(self, backend: BackendClient, city: str = "", parent=None) -> None:
        super().__init__(parent)
        self._backend = backend
        self._city = city

    def run(self) -> None:
        try:
            data = self._backend.get_tomorrow_weather(self._city)
        except Exception as exc:  # noqa: BLE001 - 后台线程不向 UI 抛未捕获异常
            self.failed.emit(f"{type(exc).__name__}: {exc}")
            return
        tip = data.get("tip") if isinstance(data, dict) else ""
        rain = data.get("rain") if isinstance(data, dict) else None
        date = data.get("date") if isinstance(data, dict) else ""
        city = (data.get("city") if isinstance(data, dict) else "") or self._city or "后端默认城市"
        # 控制台留一行结果，人工验收时能直接看出查没查到、有没有雨
        print(f"[weather-tip] {city} {date} rain={rain} tip={tip or '-'}", flush=True)
        if tip:
            self.tip.emit(str(tip))
