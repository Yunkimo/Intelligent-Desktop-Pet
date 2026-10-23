"""桌宠窗口显示/关闭时的状态角标测试。"""

from unittest.mock import Mock

from PyQt6.QtGui import QCloseEvent, QShowEvent
from PyQt6.QtWidgets import QMenu, QWidget

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


def _stub_close_dependencies(window: PetWindow) -> None:
    window.hotkey = None
    window.health = Mock()
    window.ws = Mock()
    window.agent_status = Mock()
    window.codex_agent_status = Mock()
    window.memory = Mock()
    window._cleanup_tts_tmp = Mock()
    window.status_badge = Mock()
    window.codex_status_badge = Mock()
    window.bubble = Mock()
    window.tray = Mock()


def test_close_event_cleans_up_and_quits(qapp, monkeypatch):
    """托盘关闭时，关闭桌宠必须一并关闭角标、气泡与托盘，并显式退出事件循环。

    两者都是独立顶层浮窗；主窗口又带 Qt.Tool 标志，Qt 不会自动
    quitOnLastWindowClosed，不显式退出时启动脚本的控制台一直不结束。
    """
    import pet.window as window_module

    fake_app = Mock()
    monkeypatch.setattr(window_module, "QApplication", Mock(instance=Mock(return_value=fake_app)))

    window = _bare_window()
    window.settings = Mock(tray_enabled=False)
    _stub_close_dependencies(window)

    window.closeEvent(QCloseEvent())

    window.status_badge.close.assert_called_once()
    window.codex_status_badge.close.assert_called_once()
    window.codex_agent_status.stop.assert_called_once()
    window.agent_status.stop.assert_called_once()
    window.bubble.close.assert_called_once()
    window.tray.hide.assert_called_once()
    fake_app.quit.assert_called_once()


def test_close_with_tray_hides_instead_of_quitting(qapp, monkeypatch):
    """托盘启用时，关闭窗口只隐藏，不执行收尾也不退出事件循环。"""
    import pet.window as window_module

    fake_app = Mock()
    monkeypatch.setattr(window_module, "QApplication", Mock(instance=Mock(return_value=fake_app)))
    window = _bare_window()
    window.settings = Mock(tray_enabled=True)
    window.hide_to_tray = Mock()

    event = QCloseEvent()
    window.closeEvent(event)

    window.hide_to_tray.assert_called_once()
    assert event.isAccepted() is False
    fake_app.quit.assert_not_called()


def test_close_with_quitting_flag_tears_down_even_with_tray(qapp, monkeypatch):
    """托盘「退出」置 _quitting 后，关闭窗口必须真正收尾。"""
    import pet.window as window_module

    fake_app = Mock()
    monkeypatch.setattr(window_module, "QApplication", Mock(instance=Mock(return_value=fake_app)))
    window = _bare_window()
    window.settings = Mock(tray_enabled=True)
    window._quitting = True
    _stub_close_dependencies(window)

    window.closeEvent(QCloseEvent())

    window.status_badge.close.assert_called_once()
    window.codex_status_badge.close.assert_called_once()
    window.codex_agent_status.stop.assert_called_once()
    window.bubble.close.assert_called_once()
    window.tray.hide.assert_called_once()
    fake_app.quit.assert_called_once()


def test_command_table_puts_hide_to_tray_at_top(qapp):
    """桌宠右键菜单顶部是「隐藏至托盘」，托盘菜单则复用其余命令。"""
    window = _bare_window()
    window.settings = Mock(tray_enabled=True, personas={})
    window._choose_image = Mock()
    window._build_persona_menu = Mock(return_value=QMenu())
    window._set_voice_hotkey = Mock()
    window._toggle_claude_monitor = Mock()
    window._toggle_codex_monitor = Mock()
    window._debug_backend = Mock()
    window._quit = Mock()

    commands = window._build_commands()

    assert commands[0].label == "隐藏至托盘"
    assert commands[0].enabled() is True
    assert commands[-1].label == "退出"
    commands[-1].execute()
    window._quit.assert_called_once()

    window.settings.tray_enabled = False
    assert commands[0].enabled() is False
    assert window._build_commands(include_hide_to_tray=False)[0].label == "切换图片…"


def test_codex_and_dual_badges_avoid_bubble(qapp):
    from PyQt6.QtCore import QRect

    from pet.status_badge import StatusBadge

    window = _bare_window()
    window.resize(300, 300)
    geo = window.screen().availableGeometry()
    window.move(geo.left() + 30, geo.bottom() - 330)
    window.status_badge = StatusBadge(window)
    window.codex_status_badge = StatusBadge(window, agent_name="Codex")
    window.bubble = QWidget()
    window.bubble.setGeometry(geo.left() + 30, geo.bottom() - 450, 240, 120)
    window.bubble.show()
    try:
        window.codex_status_badge.set_state("working")
        window._position_status_badge()
        codex_rect = QRect(window.codex_status_badge.pos(), window.codex_status_badge.size())
        assert geo.contains(codex_rect)
        assert not codex_rect.intersects(window.bubble.geometry())
        window.status_badge.set_state("waiting")
        window._position_status_badge()
        rects = [QRect(b.pos(), b.size()) for b in (window.status_badge, window.codex_status_badge)]
        assert not rects[0].intersects(rects[1])
        for rect in rects:
            assert geo.contains(rect)
            assert not rect.intersects(window.bubble.geometry())
    finally:
        window.status_badge.close()
        window.codex_status_badge.close()
        window.bubble.close()


def test_position_skips_manually_positioned_badge(qapp):
    """被手动拖过的角标不参与自动摆位，其余角标仍正常跟随桌宠。"""
    from PyQt6.QtCore import QPoint

    from pet.status_badge import StatusBadge

    window = _bare_window()
    window.resize(300, 300)
    geo = window.screen().availableGeometry()
    window.move(geo.left() + 30, geo.bottom() - 330)
    window.status_badge = StatusBadge(window)
    window.codex_status_badge = StatusBadge(window, agent_name="Codex")
    window.bubble = QWidget()
    window.bubble.setGeometry(geo.left() + 30, geo.bottom() - 450, 240, 120)
    window.bubble.hide()
    try:
        window.status_badge.set_state("working")
        window.codex_status_badge.set_state("waiting")
        window._position_status_badge()
        # 手动把 Claude 角标拖到固定位置后，自动摆位不应再覆盖它
        window.status_badge._user_moved = True
        window.status_badge.move(geo.left() + 10, geo.top() + 10)
        manual = QPoint(window.status_badge.pos())
        window._position_status_badge()
        assert window.status_badge.pos() == manual
        # Codex 角标仍自动摆位，且不会落到手动角标的同一位置
        assert window.codex_status_badge.pos() != manual
    finally:
        window.status_badge.close()
        window.codex_status_badge.close()
        window.bubble.close()
