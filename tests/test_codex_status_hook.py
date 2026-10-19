"""Codex lifecycle event mapping and status-file writing tests."""

import io
import json

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
