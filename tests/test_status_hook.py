"""Claude Code status hook 测试：事件映射与状态文件写入。"""

import json
import os
import subprocess
import sys
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "claude_status_hook.py"


def _run(payload: dict, status_path: Path) -> subprocess.CompletedProcess:
    env = os.environ.copy()
    env["IDP_AGENT_STATUS_FILE"] = str(status_path)
    return subprocess.run(
        [sys.executable, str(SCRIPT)],
        input=json.dumps(payload).encode("utf-8"),
        capture_output=True,
        env=env,
        check=True,
    )


def test_hook_maps_stop_to_done(tmp_path):
    status = tmp_path / "status.json"
    _run({"hook_event_name": "Stop", "session_id": "s1"}, status)

    data = json.loads(status.read_text(encoding="utf-8"))
    assert data["state"] == "done"
    assert data["event"] == "Stop"
    assert data["session_id"] == "s1"
    assert isinstance(data["ts"], float)


def test_hook_maps_user_prompt_and_permission_notification(tmp_path):
    status = tmp_path / "status.json"
    _run({"hook_event_name": "UserPromptSubmit", "session_id": "s1"}, status)
    assert json.loads(status.read_text(encoding="utf-8"))["state"] == "working"

    _run(
        {
            "hook_event_name": "Notification",
            "session_id": "s1",
            "message": "Claude needs your permission to use Bash",
        },
        status,
    )
    assert json.loads(status.read_text(encoding="utf-8"))["state"] == "waiting"


def test_hook_ignores_idle_notification(tmp_path):
    status = tmp_path / "status.json"
    _run({"hook_event_name": "Stop", "session_id": "s1"}, status)

    _run(
        {
            "hook_event_name": "Notification",
            "session_id": "s1",
            "message": "Claude is waiting for your input",
        },
        status,
    )
    assert json.loads(status.read_text(encoding="utf-8"))["state"] == "done"


def test_hook_uses_notification_type_when_present(tmp_path):
    status = tmp_path / "status.json"
    for ntype in ("idle_prompt", "agent_completed"):
        _run(
            {
                "hook_event_name": "Notification",
                "session_id": "s1",
                "notification_type": ntype,
            },
            status,
        )
        assert not status.exists()

    _run(
        {
            "hook_event_name": "Notification",
            "session_id": "s1",
            "notification_type": "permission_prompt",
        },
        status,
    )
    assert json.loads(status.read_text(encoding="utf-8"))["state"] == "waiting"


def test_hook_maps_tool_events_to_working(tmp_path):
    status = tmp_path / "status.json"
    for event in ("PreToolUse", "PostToolUse"):
        _run({"hook_event_name": event, "session_id": "s1"}, status)
        assert json.loads(status.read_text(encoding="utf-8"))["state"] == "working"


def test_hook_ignores_unknown_event(tmp_path):
    status = tmp_path / "status.json"
    _run({"hook_event_name": "SubagentStop", "session_id": "s1"}, status)
    assert not status.exists()
