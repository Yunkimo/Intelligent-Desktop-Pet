"""Codex hooks.json merge, idempotency, and malformed-file protection."""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from scripts.install_codex_status_hook import EVENTS, _command, install


def test_install_merges_preserves_existing_and_is_idempotent(tmp_path):
    settings = tmp_path / "hooks.json"
    settings.write_text(
        json.dumps(
            {
                "custom": {"keep": True},
                "hooks": {"Stop": [{"hooks": [{"type": "command", "command": "existing"}]}]},
            }
        ),
        encoding="utf-8",
    )
    script = tmp_path / "codex_status_hook.py"

    added = install(settings, tmp_path / "python.exe", script)
    assert set(added) == set(EVENTS)
    result = json.loads(settings.read_text(encoding="utf-8"))
    assert result["custom"] == {"keep": True}
    stop_handlers = [item for group in result["hooks"]["Stop"] for item in group["hooks"]]
    assert any(item["command"] == "existing" for item in stop_handlers)
    assert any(
        item.get("statusMessage") == f"IDP Codex monitor: {script.as_posix()}"
        for item in stop_handlers
    )
    assert install(settings, tmp_path / "python.exe", script) == []


@pytest.mark.parametrize("contents", ["not json", "[]", '{"hooks": []}', '{"hooks": {"Stop": {}}}'])
def test_malformed_settings_are_not_overwritten(tmp_path, contents):
    settings = tmp_path / "hooks.json"
    settings.write_text(contents, encoding="utf-8")
    with pytest.raises(ValueError):
        install(settings, tmp_path / "python.exe", tmp_path / "hook.py")
    assert settings.read_text(encoding="utf-8") == contents


@pytest.mark.parametrize("outer_shell", ["cmd", "powershell"] if os.name == "nt" else ["sh"])
def test_generated_command_runs_hook_and_handles_spaces(tmp_path, monkeypatch, outer_shell):
    script = tmp_path / "folder with spaces" / "codex_status_hook.py"
    script.parent.mkdir()
    script.write_text(
        "import json, os, sys\n"
        "from pathlib import Path\n"
        "payload = json.loads(sys.stdin.buffer.read())\n"
        "Path(os.environ['IDP_CODEX_STATUS_FILE']).write_text(payload['hook_event_name'])\n",
        encoding="utf-8",
    )
    output = tmp_path / "status file.json"
    monkeypatch.setenv("IDP_CODEX_STATUS_FILE", str(output))
    command = _command(Path(sys.executable), script)
    completed = subprocess.run(
        ["powershell", "-NoProfile", "-Command", command]
        if outer_shell == "powershell"
        else command,
        input='{"hook_event_name":"Stop"}',
        text=True,
        shell=outer_shell != "powershell",
        capture_output=True,
        timeout=10,
    )
    assert completed.returncode == 0, completed.stderr
    assert output.read_text(encoding="utf-8") == "Stop"
