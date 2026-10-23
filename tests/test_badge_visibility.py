"""状态角标用户级显隐测试：独立于桌宠与监控开关。"""

from unittest.mock import Mock

from PyQt6.QtWidgets import QWidget

from pet.window import PetWindow


def _bare_window() -> PetWindow:
    """不跑 __init__ 的重活，只初始化 QWidget 基类。"""
    window = PetWindow.__new__(PetWindow)
    QWidget.__init__(window)
    return window


def _make_window(visible: bool = True) -> PetWindow:
    window = _bare_window()
    window.settings = Mock(status_badges_visible=visible)
    window.status_badge = Mock()
    window.codex_status_badge = Mock()
    window._position_status_badge = Mock()
    window._status_badges_visible = visible
    return window


def test_toggle_hides_both_badges_and_persists(qapp):
    window = _make_window(visible=True)

    window._toggle_status_badges()

    assert window._status_badges_visible is False
    window.settings.update_status_badges_visible.assert_called_once_with(False)
    window.status_badge.set_user_visible.assert_called_once_with(False)
    window.codex_status_badge.set_user_visible.assert_called_once_with(False)
    window._position_status_badge.assert_called_once_with()


def test_toggle_back_shows_both_badges(qapp):
    window = _make_window(visible=False)

    window._toggle_status_badges()

    assert window._status_badges_visible is True
    window.settings.update_status_badges_visible.assert_called_once_with(True)
    window.status_badge.set_user_visible.assert_called_once_with(True)
    window.codex_status_badge.set_user_visible.assert_called_once_with(True)
    window._position_status_badge.assert_called_once_with()
