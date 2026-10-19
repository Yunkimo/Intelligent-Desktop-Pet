"""状态钩子安装封装测试：安装器调用、路径加载与工具探测。"""

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

import pet.hook_install as hook_install


def _fake_installer(added: list[str], exc=None):
    """构造假安装模块，并记录 install 收到的参数。"""
    calls: list[tuple[Path, Path, Path]] = []

    def install(settings_path: Path, python_exe: Path, hook_script: Path) -> list[str]:
        calls.append((settings_path, python_exe, hook_script))
        if exc is not None:
            raise exc
        return added

    module = SimpleNamespace(
        install=install,
        DEFAULT_SETTINGS=Path("C:/fake/settings.json"),
        HOOK_SCRIPT=Path("C:/fake/hook.py"),
    )
    return module, calls


def test_ensure_claude_hooks_uses_installer_defaults(monkeypatch):
    module, calls = _fake_installer(["Stop"])
    loaded: list[str] = []

    def load(filename: str):
        loaded.append(filename)
        return module

    monkeypatch.setattr(hook_install, "_load_installer", load)

    assert hook_install.ensure_claude_hooks() == ["Stop"]
    assert loaded == ["install_claude_status_hook.py"]
    assert calls == [(module.DEFAULT_SETTINGS, Path(sys.executable), module.HOOK_SCRIPT)]


def test_ensure_codex_hooks_uses_installer_defaults(monkeypatch):
    module, calls = _fake_installer(["UserPromptSubmit"])
    loaded: list[str] = []

    def load(filename: str):
        loaded.append(filename)
        return module

    monkeypatch.setattr(hook_install, "_load_installer", load)

    assert hook_install.ensure_codex_hooks() == ["UserPromptSubmit"]
    assert loaded == ["install_codex_status_hook.py"]
    assert calls == [(module.DEFAULT_SETTINGS, Path(sys.executable), module.HOOK_SCRIPT)]


def test_ensure_hooks_returns_empty_when_already_installed(monkeypatch):
    module, _ = _fake_installer([])
    monkeypatch.setattr(hook_install, "_load_installer", lambda _filename: module)

    assert hook_install.ensure_claude_hooks() == []
    assert hook_install.ensure_codex_hooks() == []


def test_ensure_claude_hooks_propagates_value_error(monkeypatch):
    module, _ = _fake_installer([], exc=ValueError("无效 JSON"))
    monkeypatch.setattr(hook_install, "_load_installer", lambda _filename: module)

    with pytest.raises(ValueError, match="无效 JSON"):
        hook_install.ensure_claude_hooks()


def test_ensure_codex_hooks_propagates_os_error(monkeypatch):
    module, _ = _fake_installer([], exc=OSError("没有写入权限"))
    monkeypatch.setattr(hook_install, "_load_installer", lambda _filename: module)

    with pytest.raises(OSError, match="没有写入权限"):
        hook_install.ensure_codex_hooks()


def test_load_installer_handles_path_with_spaces(tmp_path, monkeypatch):
    script_dir = tmp_path / "scripts with space"
    script_dir.mkdir()
    (script_dir / "installer.py").write_text("VALUE = 42\n", encoding="utf-8")
    monkeypatch.setattr(hook_install, "_SCRIPT_DIR", script_dir)

    module = hook_install._load_installer("installer.py")

    assert module.VALUE == 42


def test_load_installer_missing_file_raises_import_error(tmp_path, monkeypatch):
    monkeypatch.setattr(hook_install, "_SCRIPT_DIR", tmp_path)

    with pytest.raises(ImportError, match="找不到安装脚本"):
        hook_install._load_installer("missing.py")


def test_claude_code_installed_detects_home_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))

    assert hook_install.claude_code_installed() is False

    (tmp_path / ".claude").mkdir()
    assert hook_install.claude_code_installed() is True


def test_codex_installed_prefers_codex_home_env(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    custom = tmp_path / "custom codex"
    custom.mkdir()
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))
    monkeypatch.delenv("CODEX_HOME", raising=False)

    assert hook_install.codex_installed() is False

    monkeypatch.setenv("CODEX_HOME", str(custom))
    assert hook_install.codex_installed() is True

    monkeypatch.delenv("CODEX_HOME")
    (home / ".codex").mkdir()
    assert hook_install.codex_installed() is True
