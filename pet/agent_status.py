"""Claude Code 回合状态监控：轮询 hook 写入的状态文件。"""

import json
import time
from pathlib import Path

from PyQt6.QtCore import QObject, QTimer, pyqtSignal

VALID_STATES = {"working", "waiting", "done", "idle", "unknown"}


def read_status(path: Path) -> dict | None:
    """读取状态文件；不存在、损坏或字段非法时返回 None。"""
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    state = data.get("state")
    if state not in VALID_STATES:
        return None
    ts = data.get("ts", 0.0)
    if not isinstance(ts, (int, float)):
        ts = 0.0
    # 兼容毫秒时间戳，避免 hook 端单位不一致时把状态误判为过期
    if ts > 1e12:
        ts /= 1000.0
    return {
        "state": state,
        "ts": float(ts),
        "event": str(data.get("event") or ""),
        "session_id": str(data.get("session_id") or ""),
    }


class AgentStatusMonitor(QObject):
    """把 Claude Code 的 hook 状态文件转换为 Qt 信号。

    状态文件由 scripts/claude_status_hook.py 原子写入；这里用轮询而不是
    QFileSystemWatcher，因为原子替换会让监听单个文件的 watcher 失效。
    """

    state_changed = pyqtSignal(str)

    def __init__(
        self,
        path: Path,
        stale_seconds: float = 300.0,
        interval_ms: int = 500,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.path = Path(path)
        self.stale_seconds = stale_seconds
        self._state: str | None = None
        self._last_ts: float = 0.0
        self._timer = QTimer(self)
        self._timer.setInterval(interval_ms)
        self._timer.timeout.connect(self.poll)

    @property
    def state(self) -> str | None:
        return self._state

    def start(self) -> None:
        """立即读一次，再按间隔轮询；重新开启时强制刷新一次角标。"""
        self._state = None
        self.poll()
        self._timer.start()

    def stop(self) -> None:
        self._timer.stop()

    def poll(self) -> None:
        """读取一次状态文件；状态变化时发一次信号。"""
        info = read_status(self.path)
        if info is None:
            # 文件尚未生成或正被原子替换：进行中状态短暂保持，超时后转未知；
            # 已结束状态在文件消失后回到 idle。
            if self._state in {"working", "waiting"}:
                if self._is_stale():
                    self._emit("unknown")
            elif self._state is None or self._state in {"done", "unknown"}:
                self._emit("idle")
            return

        self._last_ts = info["ts"]
        state = info["state"]
        # done 是终态，久未更新也应保留「本轮完成」；只有进行中的状态会过期
        if state in {"working", "waiting"} and self._is_stale():
            state = "unknown"
        self._emit(state)

    def _is_stale(self) -> bool:
        return self._last_ts > 0 and time.time() - self._last_ts > self.stale_seconds

    def _emit(self, state: str) -> None:
        if state != self._state:
            self._state = state
            self.state_changed.emit(state)
