"""天气提示：每晚到点查一次次日是否有雨，有雨时提醒带伞。

分两层：WeatherTipMonitor 只负责「到点触发一次」（同一天不重复），真正的
网络查询在 WeatherTipWorker(QThread) 里做，不阻塞 UI；有雨时发 tip 信号，
窗口据此弹气泡并按语音开关决定是否播报。网络失败/未绑定账号静默跳过，不刷屏。
"""

from datetime import datetime

from PyQt6.QtCore import QObject, QThread, QTimer, pyqtSignal

from .backend_client import BackendClient

_CHECK_INTERVAL_MS = 60_000  # 每分钟对一次时间


class WeatherTipMonitor(QObject):
    """到点发一次 check_due；同一天只发一次，跨天自动复位。"""

    check_due = pyqtSignal()

    def __init__(self, hour: int, clock=None, parent=None) -> None:
        super().__init__(parent)
        self._hour = hour
        self._clock = clock or datetime.now
        self._fired_dates: set[str] = set()
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
        if key in self._fired_dates:
            return
        self._fired_dates.add(key)
        self.check_due.emit()


class WeatherTipWorker(QThread):
    """后台查次日天气；只有「有雨且带提示文案」才发 tip，其余情况一律静默。"""

    tip = pyqtSignal(str)
    failed = pyqtSignal(str)

    def __init__(self, backend: BackendClient, city: str, parent=None) -> None:
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
        if tip:
            self.tip.emit(str(tip))
