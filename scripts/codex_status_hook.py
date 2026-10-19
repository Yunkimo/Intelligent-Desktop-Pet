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


def write_status(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    status = {
        "state": payload["state"],
        "event": payload["event"],
        "session_id": str(payload.get("session_id") or ""),
        "ts": time.time(),
    }
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
                path, {"state": state, "event": event, "session_id": payload.get("session_id")}
            )
    except Exception:
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
