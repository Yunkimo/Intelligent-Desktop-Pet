"""角标右键菜单与 Agent 状态音效的接线测试。"""

from unittest.mock import Mock

from PyQt6.QtWidgets import QWidget

from pet.window import PetWindow


def _bare_window(claude_on: bool = True, codex_on: bool = False) -> PetWindow:
    """只初始化 QWidget 基类，把命令表依赖的方法全部换成 Mock。"""
    window = PetWindow.__new__(PetWindow)
    QWidget.__init__(window)
    window.settings = Mock(monitor_claude=claude_on, monitor_codex=codex_on)
    window._status_badges_visible = True
    window._toggle_claude_monitor = Mock()
    window._toggle_codex_monitor = Mock()
    window._toggle_status_badges = Mock()
    window._show_usage_dialog = Mock()
    window._quit = Mock()
    return window


def _by_label(window: PetWindow) -> dict:
    return {command.label: command for command in window._badge_commands()}


def test_badge_menu_order(qapp):
    labels = [command.label for command in _bare_window()._badge_commands()]

    assert labels == ["监控 Claude", "监控 Codex", "显示状态角标", "查看余额", "退出"]


def test_badge_menu_reuses_window_actions(qapp):
    window = _bare_window()
    commands = _by_label(window)

    assert commands["监控 Claude"].checkable is True
    assert commands["监控 Claude"].checked() is True
    assert commands["监控 Codex"].checkable is True
    assert commands["监控 Codex"].checked() is False
    assert commands["显示状态角标"].checkable is True

    commands["查看余额"].execute()
    window._show_usage_dialog.assert_called_once()

    commands["退出"].execute()
    window._quit.assert_called_once()


def test_badge_menu_quit_is_last(qapp):
    assert _bare_window()._badge_commands()[-1].label == "退出"


def test_agent_status_plays_cue_and_updates_badge(qapp):
    window = _bare_window()
    window.status_badge = Mock()
    window.sfx = Mock()
    window._position_status_badge = Mock()

    window._on_agent_status("waiting")

    window.status_badge.set_state.assert_called_once_with("waiting")
    window.sfx.play.assert_called_once_with("waiting")
    window._position_status_badge.assert_called_once()


def test_codex_status_plays_same_cues(qapp):
    window = _bare_window()
    window.codex_status_badge = Mock()
    window.sfx = Mock()
    window._position_status_badge = Mock()

    window._on_codex_status("done")

    window.codex_status_badge.set_state.assert_called_once_with("done")
    window.sfx.play.assert_called_once_with("done")
