"""Codex lifecycle event mapping and status-file writing tests."""

import io
import json
from concurrent.futures import ThreadPoolExecutor

import pytest

from scripts import codex_status_hook as hook


def test_event_mapping_writes_only_status_metadata(tmp_path, monkeypatch):
    path = tmp_path / "codex-status.json"
    monkeypatch.setenv("IDP_CODEX_STATUS_FILE", str(path))
    monkeypatch.setattr(
        hook.sys,
        "stdin",
        io.TextIOWrapper(
            io.BytesIO(
                json.dumps(
                    {
                        "hook_event_name": "PermissionRequest",
                        "session_id": "session-1",
                        "prompt": "private prompt",
                        "tool_input": {"command": "private command"},
                    }
                ).encode()
            )
        ),
    )

    assert hook.main() == 0
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["state"] == "waiting"
    assert payload["event"] == "PermissionRequest"
    assert payload["session_id"] == "session-1"
    assert "prompt" not in payload
    assert "tool_input" not in payload
    assert isinstance(payload["ts"], float)


def test_unknown_event_and_bad_input_are_noops(tmp_path, monkeypatch):
    path = tmp_path / "missing.json"
    monkeypatch.setenv("IDP_CODEX_STATUS_FILE", str(path))
    monkeypatch.setattr(hook.sys, "stdin", io.TextIOWrapper(io.BytesIO(b"not json")))
    assert hook.main() == 0
    assert not path.exists()


def test_all_supported_events_have_expected_states():
    assert hook.EVENT_STATES == {
        "SessionStart": "idle",
        "UserPromptSubmit": "working",
        "PreToolUse": "working",
        "PostToolUse": "working",
        "PermissionRequest": "waiting",
        "Stop": "done",
        "Interrupt": "unknown",
        "SessionEnd": "idle",
    }


def _send(path, event, session="session-1", turn="turn-1"):
    hook.write_status(
        path,
        {"state": hook.EVENT_STATES[event], "event": event, "session_id": session, "turn_id": turn},
    )
    return json.loads(path.read_text(encoding="utf-8"))


@pytest.mark.parametrize("turn", ["turn-1", ""])
def test_done_survives_late_tools_until_new_prompt(tmp_path, turn):
    path = tmp_path / "status.json"
    _send(path, "UserPromptSubmit", turn=turn)
    _send(path, "Stop", turn=turn)
    completed = path.read_bytes()
    for event in ("PreToolUse", "PostToolUse", "PermissionRequest", "SessionStart"):
        _send(path, event, turn=turn)
        assert path.read_bytes() == completed
    assert _send(path, "UserPromptSubmit", turn="turn-2")["state"] == "working"
    assert _send(path, "PermissionRequest", turn="turn-2")["state"] == "waiting"
    assert _send(path, "PostToolUse", turn="turn-2")["state"] == "working"


def test_old_turn_cannot_finish_or_restart_new_turn(tmp_path):
    path = tmp_path / "status.json"
    _send(path, "UserPromptSubmit")
    _send(path, "UserPromptSubmit", turn="turn-2")
    for event in ("Stop", "PreToolUse", "PostToolUse"):
        result = _send(path, event)
        assert result["turn_id"] == "turn-2"
        assert result["event"] == "UserPromptSubmit"


def test_only_prompt_from_other_session_switches_display(tmp_path):
    path = tmp_path / "status.json"
    _send(path, "UserPromptSubmit")
    _send(path, "Stop")
    for event in ("SessionStart", "PreToolUse", "PostToolUse", "Stop", "SessionEnd"):
        result = _send(path, event, session="session-2")
        assert result["session_id"] == "session-1"
        assert result["state"] == "done"
    assert _send(path, "UserPromptSubmit", session="session-2")["session_id"] == "session-2"
    assert _send(path, "Stop")["session_id"] == "session-2"


def test_concurrent_stop_and_tool_events_leave_done(tmp_path):
    path = tmp_path / "status.json"
    _send(path, "UserPromptSubmit")
    with ThreadPoolExecutor(max_workers=6) as pool:
        list(
            pool.map(
                lambda event: _send(path, event),
                ["PostToolUse"] * 10 + ["Stop"] + ["PreToolUse"] * 10,
            )
        )
    assert json.loads(path.read_text(encoding="utf-8"))["state"] == "done"
