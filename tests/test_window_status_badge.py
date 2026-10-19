"""桌宠窗口显示时的浮层定位测试。"""

from PyQt6.QtGui import QShowEvent
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
