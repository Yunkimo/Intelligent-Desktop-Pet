"""健康关怀：检测用户「连续久坐」时长，超阈值提醒起来活动。

Windows 用 GetLastInputInfo 拿「空闲时长」，1 分钟内无键鼠输入视为离开座位
（久坐计时清零）；否则视为仍在电脑前，累计久坐时长，
满一个间隔就发一次提醒信号。其它平台无该 API，空闲时长恒为 0（即视为始终在座），
保证跨平台不崩。
"""

import ctypes
import time

from PyQt6.QtCore import QObject, QTimer, pyqtSignal

_CHECK_INTERVAL_MS = 15_000  # 每 15 秒检测一次
_AWAY_SECS = 60.0  # 1 分钟内无键鼠输入视为离座，久坐重新计时


class _IdleTimer:
    """读取系统空闲时长（秒）。"""

    def __init__(self) -> None:
        self._get_last_input = None
        self._get_tick = None
        if not hasattr(ctypes, "windll"):
            return
        try:
            self._get_last_input = ctypes.windll.user32.GetLastInputInfo
            self._get_tick = ctypes.windll.kernel32.GetTickCount
        except Exception:
            self._get_last_input = None
            self._get_tick = None

    def idle_seconds(self) -> float:
        if self._get_last_input is None or self._get_tick is None:
            return 0.0

        class _LastInputInfo(ctypes.Structure):
            _fields_ = [("cbSize", ctypes.c_uint), ("dwTime", ctypes.c_uint)]

        info = _LastInputInfo()
        info.cbSize = ctypes.sizeof(_LastInputInfo)
        if not self._get_last_input(ctypes.byref(info)):
            return 0.0
        elapsed_ms = self._get_tick() - info.dwTime
        return max(0.0, elapsed_ms / 1000.0)


class HealthMonitor(QObject):
    """用 QTimer 周期性统计连续久坐时长，每满一个间隔发一次提醒信号。

    久坐 = 未离开座位（空闲时长 < _AWAY_SECS）的连续时间；满 sedentary_interval_min
    分钟提醒一次，之后每再满一个间隔再提醒；离开座位后计时与提醒周期一并清零。
    """

    sedentary_due = pyqtSignal()

    def __init__(self, settings, idle_source=None, clock=None, parent=None) -> None:
        super().__init__(parent)
        self._settings = settings
        self._idle = idle_source or _IdleTimer()
        self._clock = clock or time.monotonic
        self._session_start: float | None = None  # 本次久坐开始时刻
        self._last_due_at: float | None = None  # 上次提醒时刻

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._check)

    def start(self) -> None:
        """按配置启用；health_enabled 关闭时不启动定时器。"""
        if not self._settings.health_enabled:
            return
        self._timer.start(_CHECK_INTERVAL_MS)

    def stop(self) -> None:
        self._timer.stop()

    def _check(self) -> None:
        idle = self._idle.idle_seconds()
        now = self._clock()
        # 1 分钟无输入 → 视为离开座位，计时与提醒周期一并清零
        if idle >= _AWAY_SECS:
            self._session_start = None
            self._last_due_at = None
            return
        # 仍在电脑前：开始（或延续）久坐计时
        if self._session_start is None:
            self._session_start = now
        sitting = now - self._session_start
        minutes = self._settings.sedentary_interval_min
        if minutes <= 0:
            return
        threshold = minutes * 60
        if sitting >= threshold and (
            self._last_due_at is None or now - self._last_due_at >= threshold
        ):
            self._last_due_at = now
            self.sedentary_due.emit()
