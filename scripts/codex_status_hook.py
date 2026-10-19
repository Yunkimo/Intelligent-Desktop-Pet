"""Write Codex lifecycle hook events to the desktop pet's status file.

Only event name, session id, and timestamp are stored; prompt and tool contents
are never read or persisted. The hook always exits successfully so monitoring
cannot block a Codex turn.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import time
from contextlib import contextmanager
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DEFAULT_STATUS_PATH = BASE_DIR / "data" / "codex-agent-status.json"

EVENT_STATES = {
    "SessionStart": "idle",
    "UserPromptSubmit": "working",
    "PreToolUse": "working",
    "PostToolUse": "working",
    "PermissionRequest": "waiting",
    "Stop": "done",
    "Interrupt": "unknown",
    "SessionEnd": "idle",
}


def read_payload() -> dict:
    try:
        data = json.loads(sys.stdin.buffer.read().decode("utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


@contextmanager
def _status_lock(path: Path):
    """跨进程串行化读取、判断和写入，避免并发 hook 覆盖完成状态。"""
    with path.with_suffix(".lock").open("a+b") as stream:
        if stream.tell() == 0:
            stream.write(b"0")
            stream.flush()
        deadline = time.monotonic() + 1
        while True:
            try:
                stream.seek(0)
                if os.name == "nt":
                    import msvcrt

                    msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl

                    fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except OSError:
                if time.monotonic() >= deadline:
                    raise
                time.sleep(0.01)
        try:
            yield
        finally:
            stream.seek(0)
            if os.name == "nt":
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)


def _accept_event(previous: dict, incoming: dict) -> bool:
    """跟随最近收到用户消息的会话，拒绝同回合结束后的迟到工具事件。"""
    if not previous or incoming["event"] == "UserPromptSubmit":
        return True
    if previous.get("session_id") != incoming["session_id"]:
        # 新会话的启动/后台工具不能抢占当前显示；用户消息可以切换。
        return not previous.get("session_id")
    old_turn = previous.get("turn_id", "")
    new_turn = incoming.get("turn_id", "")
    if old_turn and new_turn and old_turn != new_turn:
        return False
    if previous.get("event") in {"Stop", "Interrupt", "SessionEnd"}:
        return incoming["event"] == "SessionEnd"
    return True


def write_status(path: Path, payload: dict) -> None:
    """原子更新回合状态，只保存事件元数据。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    with _status_lock(path):
        _write_status_locked(path, payload)


def _write_status_locked(path: Path, payload: dict) -> None:
    status = {
        "state": payload["state"],
        "event": payload["event"],
        "session_id": str(payload.get("session_id") or ""),
        "turn_id": str(payload.get("turn_id") or ""),
        "ts": time.time(),
    }
    try:
        previous = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(previous, dict):
            previous = {}
    except (OSError, ValueError):
        previous = {}
    if not _accept_event(previous, status):
        return
    if status["event"] != "UserPromptSubmit" and not status["turn_id"]:
        status["turn_id"] = previous.get("turn_id", "")
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".codex-status-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(status, stream, ensure_ascii=False)
        os.replace(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def main() -> int:
    try:
        payload = read_payload()
        event = str(payload.get("hook_event_name") or "")
        state = EVENT_STATES.get(event)
        if state:
            path = Path(os.environ.get("IDP_CODEX_STATUS_FILE", DEFAULT_STATUS_PATH))
            write_status(
                path,
                {
                    "state": state,
                    "event": event,
                    "session_id": payload.get("session_id"),
                    "turn_id": payload.get("turn_id"),
                },
            )
    except Exception:
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
