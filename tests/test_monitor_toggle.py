"""监控开关测试：开启自动安装钩子、失败回滚与气泡提示。"""

from unittest.mock import Mock

from PyQt6.QtWidgets import QWidget

import pet.window as window_module
from pet.window import PetWindow


def _bare_window() -> PetWindow:
    """不跑 __init__ 的重活，只初始化 QWidget 基类。"""
    window = PetWindow.__new__(PetWindow)
    QWidget.__init__(window)
    return window


def _make_window(monitor_claude: bool = False, monitor_codex: bool = False) -> PetWindow:
    window = _bare_window()
    window.settings = Mock(monitor_claude=monitor_claude, monitor_codex=monitor_codex)
    window.agent_status = Mock()
    window.codex_agent_status = Mock()
    window.status_badge = Mock()
    window.codex_status_badge = Mock()
    window.bubble = Mock()
    window._position_status_badge = Mock()
    return window


# ---------- Claude Code ----------
def test_enable_claude_installs_hooks_and_mentions_restart(qapp, monkeypatch):
    window = _make_window()
    ensure = Mock(return_value=["Stop"])
    monkeypatch.setattr(window_module, "ensure_claude_hooks", ensure)
    monkeypatch.setattr(window_module, "claude_code_installed", lambda: True)

    window._toggle_claude_monitor()

    ensure.assert_called_once_with()
    window.settings.update_monitor_claude.assert_called_once_with(True)
    window.agent_status.start.assert_called_once_with()
    text = window.bubble.set_text.call_args.args[0]
    assert "已装好 Claude Code 状态钩子" in text
    assert "重启 Claude Code" in text


def test_enable_claude_keeps_message_when_hooks_exist(qapp, monkeypatch):
    window = _make_window()
    monkeypatch.setattr(window_module, "ensure_claude_hooks", Mock(return_value=[]))

    window._toggle_claude_monitor()

    window.settings.update_monitor_claude.assert_called_once_with(True)
    window.agent_status.start.assert_called_once_with()
    assert window.bubble.set_text.call_args.args[0] == "开始监控 Claude Code 啦～"


def test_enable_claude_warns_when_tool_missing(qapp, monkeypatch):
    window = _make_window()
    monkeypatch.setattr(window_module, "ensure_claude_hooks", Mock(return_value=["Stop"]))
    monkeypatch.setattr(window_module, "claude_code_installed", lambda: False)

    window._toggle_claude_monitor()

    window.settings.update_monitor_claude.assert_called_once_with(True)
    window.agent_status.start.assert_called_once_with()
    text = window.bubble.set_text.call_args.args[0]
    assert "未检测到 Claude Code" in text
    assert "钩子已写好" in text


def test_enable_claude_rolls_back_when_install_fails(qapp, monkeypatch):
    window = _make_window()
    ensure = Mock(side_effect=ValueError("配置文件损坏"))
    monkeypatch.setattr(window_module, "ensure_claude_hooks", ensure)

    window._toggle_claude_monitor()

    ensure.assert_called_once_with()
    window.settings.update_monitor_claude.assert_called_once_with(False)
    window.agent_status.start.assert_not_called()
    text = window.bubble.set_text.call_args.args[0]
    assert "Claude Code 监控开启失败" in text
    assert "配置文件损坏" in text


def test_disable_claude_skips_install(qapp, monkeypatch):
    window = _make_window(monitor_claude=True)
    ensure = Mock()
    monkeypatch.setattr(window_module, "ensure_claude_hooks", ensure)

    window._toggle_claude_monitor()

    ensure.assert_not_called()
    window.settings.update_monitor_claude.assert_called_once_with(False)
    window.agent_status.stop.assert_called_once_with()
    window.status_badge.set_state.assert_called_once_with("idle")
    assert window.bubble.set_text.call_args.args[0] == "已关闭 Claude Code 监控"


# ---------- Codex ----------
def test_enable_codex_installs_hooks_and_mentions_trust(qapp, monkeypatch):
    window = _make_window()
    ensure = Mock(return_value=["Stop"])
    monkeypatch.setattr(window_module, "ensure_codex_hooks", ensure)
    monkeypatch.setattr(window_module, "codex_installed", lambda: True)

    window._toggle_codex_monitor()

    ensure.assert_called_once_with()
    window.settings.update_monitor_codex.assert_called_once_with(True)
    window.codex_agent_status.start.assert_called_once_with()
    text = window.bubble.set_text.call_args.args[0]
    assert "已写好 Codex 状态钩子" in text
    assert "信任并重启" in text
    window._position_status_badge.assert_called_once_with()


def test_enable_codex_keeps_message_when_hooks_exist(qapp, monkeypatch):
    window = _make_window()
    monkeypatch.setattr(window_module, "ensure_codex_hooks", Mock(return_value=[]))

    window._toggle_codex_monitor()

    window.settings.update_monitor_codex.assert_called_once_with(True)
    window.codex_agent_status.start.assert_called_once_with()
    assert window.bubble.set_text.call_args.args[0] == "开始监控 Codex 啦～"
    window._position_status_badge.assert_called_once_with()


def test_enable_codex_warns_when_tool_missing(qapp, monkeypatch):
    window = _make_window()
    monkeypatch.setattr(window_module, "ensure_codex_hooks", Mock(return_value=["Stop"]))
    monkeypatch.setattr(window_module, "codex_installed", lambda: False)

    window._toggle_codex_monitor()

    window.settings.update_monitor_codex.assert_called_once_with(True)
    window.codex_agent_status.start.assert_called_once_with()
    text = window.bubble.set_text.call_args.args[0]
    assert "未检测到 Codex" in text
    assert "信任并重启" in text
    window._position_status_badge.assert_called_once_with()


def test_enable_codex_rolls_back_when_install_fails(qapp, monkeypatch):
    window = _make_window()
    ensure = Mock(side_effect=OSError("没有写入权限"))
    monkeypatch.setattr(window_module, "ensure_codex_hooks", ensure)

    window._toggle_codex_monitor()

    ensure.assert_called_once_with()
    window.settings.update_monitor_codex.assert_called_once_with(False)
    window.codex_agent_status.start.assert_not_called()
    text = window.bubble.set_text.call_args.args[0]
    assert "Codex 监控开启失败" in text
    assert "没有写入权限" in text
    window._position_status_badge.assert_called_once_with()


def test_disable_codex_skips_install(qapp, monkeypatch):
    window = _make_window(monitor_codex=True)
    ensure = Mock()
    monkeypatch.setattr(window_module, "ensure_codex_hooks", ensure)

    window._toggle_codex_monitor()

    ensure.assert_not_called()
    window.settings.update_monitor_codex.assert_called_once_with(False)
    window.codex_agent_status.stop.assert_called_once_with()
    window.codex_status_badge.set_state.assert_called_once_with("idle")
    assert window.bubble.set_text.call_args.args[0] == "已关闭 Codex 监控"
    window._position_status_badge.assert_called_once_with()
