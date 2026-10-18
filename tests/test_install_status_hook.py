"""本机 Claude Code hook 配置生成测试：创建、合并、幂等与异常保护。"""

import json
from pathlib import Path

import pytest

from scripts.install_claude_status_hook import EVENTS, install


def _paths():
    return Path("C:/Program Files/Python/python.exe"), Path("C:/My Repo/scripts/hook.py")


def _command() -> str:
    python_exe, hook_script = _paths()
    code = (
        f"import os,runpy; p=r'{hook_script.as_posix()}'; "
        "os.path.exists(p) and runpy.run_path(p, run_name='__main__')"
    )
    return f'"{python_exe.as_posix()}" -c "{code}"'


def test_install_creates_all_events(tmp_path):
    settings = tmp_path / ".claude" / "settings.local.json"

    added = install(settings, *_paths())

    assert added == list(EVENTS)
    data = json.loads(settings.read_text(encoding="utf-8"))
    for event in EVENTS:
        handler = data["hooks"][event][0]["hooks"][0]
        assert handler["type"] == "command"
        assert handler["command"] == _command()
        assert handler["timeout"] == 5


def test_install_preserves_existing_config_and_is_idempotent(tmp_path):
    settings = tmp_path / "settings.local.json"
    settings.write_text(
        json.dumps(
            {
                "permissions": {"allow": ["Bash(ls)"]},
                "hooks": {"Stop": [{"hooks": [{"type": "command", "command": "echo custom"}]}]},
            }
        ),
        encoding="utf-8",
    )

    first = install(settings, *_paths())
    assert "Stop" in first
    data = json.loads(settings.read_text(encoding="utf-8"))
    assert data["permissions"] == {"allow": ["Bash(ls)"]}
    assert data["hooks"]["Stop"][0]["hooks"][0]["command"] == "echo custom"
    assert data["hooks"]["Stop"][1]["hooks"][0]["command"] == _command()

    second = install(settings, *_paths())
    assert second == []
    data = json.loads(settings.read_text(encoding="utf-8"))
    assert len(data["hooks"]["Stop"]) == 2


def test_install_matches_same_command_with_backslashes(tmp_path):
    settings = tmp_path / "settings.local.json"
    stale = _command().replace("/", "\\")
    settings.write_text(
        json.dumps({"hooks": {"Stop": [{"hooks": [{"type": "command", "command": stale}]}]}}),
        encoding="utf-8",
    )

    added = install(settings, *_paths())

    assert "Stop" not in added
    data = json.loads(settings.read_text(encoding="utf-8"))
    assert len(data["hooks"]["Stop"]) == 1


def test_install_upgrades_old_direct_command_in_place(tmp_path):
    """旧版直接调用脚本；升级后应原地替换，不能再追加一个 handler。"""
    settings = tmp_path / "settings.local.json"
    python_exe, hook_script = _paths()
    old = f'"{python_exe.as_posix()}" "{hook_script.as_posix()}"'
    settings.write_text(
        json.dumps({"hooks": {"Stop": [{"hooks": [{"type": "command", "command": old}]}]}}),
        encoding="utf-8",
    )

    added = install(settings, python_exe, hook_script)

    assert "Stop" in added
    data = json.loads(settings.read_text(encoding="utf-8"))
    handlers = data["hooks"]["Stop"]
    assert len(handlers) == 1
    assert handlers[0]["hooks"][0]["command"] == _command()


def test_install_rejects_invalid_json_without_touching_file(tmp_path):
    settings = tmp_path / "settings.local.json"
    settings.write_text("{not json", encoding="utf-8")

    with pytest.raises(ValueError):
        install(settings, *_paths())

    assert settings.read_text(encoding="utf-8") == "{not json"
