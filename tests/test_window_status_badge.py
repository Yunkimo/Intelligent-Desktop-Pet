"""桌宠窗口显示/关闭时的状态角标测试。"""

from unittest.mock import Mock

from PyQt6.QtGui import QCloseEvent, QShowEvent
from PyQt6.QtWidgets import QWidget

from pet.window import PetWindow


def _bare_window() -> PetWindow:
    """不跑 __init__ 的重活，只初始化 QWidget 基类，便于单独测试事件钩子。"""
    window = PetWindow.__new__(PetWindow)
    QWidget.__init__(window)
    return window


def test_show_event_repositions_overlays(qapp):
    """窗口显示后应重新摆放气泡与角标，并在事件循环处理完显示后再校正一次。

    两者都是顶层浮窗：窗口 show 前 mapToGlobal 拿不到最终几何，showEvent
    触发时平台窗口也可能仍在默认位置，因此必须延迟到事件循环里再摆一次。
    """
    window = _bare_window()
    calls = []
    window._position_bubble = lambda: calls.append("bubble")
    window._position_status_badge = lambda: calls.append("badge")

    window.showEvent(QShowEvent())
    assert calls == ["bubble", "badge"]

    qapp.processEvents()
    assert calls == ["bubble", "badge", "bubble", "badge"]


def test_close_event_cleans_up_and_quits(qapp, monkeypatch):
    """关闭桌宠时必须一并关闭角标与气泡，并显式退出事件循环。

    两者都是独立顶层浮窗；主窗口又带 Qt.Tool 标志，Qt 不会自动
    quitOnLastWindowClosed，不显式退出时启动脚本的控制台一直不结束。
    """
    import pet.window as window_module

    fake_app = Mock()
    monkeypatch.setattr(window_module, "QApplication", Mock(instance=Mock(return_value=fake_app)))

    window = _bare_window()
    window.hotkey = None
    window.health = Mock()
    window.ws = Mock()
    window.agent_status = Mock()
    window.memory = Mock()
    window._cleanup_tts_tmp = Mock()
    window.status_badge = Mock()
    window.bubble = Mock()

    window.closeEvent(QCloseEvent())

    window.status_badge.close.assert_called_once()
    window.bubble.close.assert_called_once()
    fake_app.quit.assert_called_once()
