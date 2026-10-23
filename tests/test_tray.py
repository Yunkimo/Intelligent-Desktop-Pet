"""系统托盘测试：图标构建、命令表复用与显隐切换（offscreen 不依赖真实托盘）。"""

from unittest.mock import Mock

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QPixmap
from PyQt6.QtWidgets import QSystemTrayIcon, QWidget

from pet.bubble import SpeechBubble
from pet.commands import Command
from pet.config import Settings
from pet.status_badge import StatusBadge
from pet.tray import TrayIcon
from pet.window import PetWindow


def _bare_window() -> PetWindow:
    """不跑 __init__ 的重活，只初始化 QWidget 基类。"""
    window = PetWindow.__new__(PetWindow)
    QWidget.__init__(window)
    return window


def _settings_with_icon(tmp_path, qapp) -> Settings:
    """用临时图片代替真实素材，避免测试依赖仓库里的形象文件。"""
    pixmap = QPixmap(100, 80)
    pixmap.fill(Qt.GlobalColor.red)
    assert pixmap.save(str(tmp_path / "pet.png"))
    settings = Settings()
    settings.assets_dir = tmp_path
    settings.frames = ["pet.png"]
    return settings


def _make_tray(tmp_path, qapp, monkeypatch, enabled: bool = False) -> tuple[TrayIcon, Mock]:
    import pet.tray as tray_module

    settings = _settings_with_icon(tmp_path, qapp)
    window = _bare_window()
    window.settings = settings
    window._build_commands = Mock(
        return_value=[Command("切换图片…", lambda: None), Command("退出", lambda: None)]
    )
    monkeypatch.setattr(tray_module.autostart, "is_enabled", lambda: enabled)
    tray = TrayIcon(window, settings, parent=window)
    return tray, window


def test_icon_built_from_current_sprite(tmp_path, qapp, monkeypatch):
    tray, _ = _make_tray(tmp_path, qapp, monkeypatch)
    icon = tray._icon.icon()

    assert not icon.isNull()
    sizes = {(size.width(), size.height()) for size in icon.availableSizes()}
    assert sizes
    assert max(max(size) for size in sizes) <= 64
    assert not icon.pixmap(16, 16).isNull()


def test_menu_reuses_command_table_with_autostart_last(tmp_path, qapp, monkeypatch):
    tray, window = _make_tray(tmp_path, qapp, monkeypatch)
    tray._rebuild_menu()

    actions = tray._menu.actions()
    assert [action.text() for action in actions] == ["切换图片…", "退出", "开机自启动"]
    assert actions[-1].isCheckable()
    assert actions[-1].isChecked() is False
    window._build_commands.assert_called_once_with(include_hide_to_tray=False)


def test_about_to_show_refreshes_checked_state(tmp_path, qapp, monkeypatch):
    import pet.tray as tray_module

    tray, _ = _make_tray(tmp_path, qapp, monkeypatch, enabled=False)
    state = {"enabled": False}
    monkeypatch.setattr(tray_module.autostart, "is_enabled", lambda: state["enabled"])

    tray._menu.aboutToShow.emit()
    assert tray._menu.actions()[-1].isChecked() is False

    state["enabled"] = True
    tray._menu.aboutToShow.emit()
    assert tray._menu.actions()[-1].isChecked() is True


def test_left_click_toggles_window_only_once(tmp_path, qapp, monkeypatch):
    tray, window = _make_tray(tmp_path, qapp, monkeypatch)
    window.toggle_tray_visibility = Mock()

    tray._on_activated(QSystemTrayIcon.ActivationReason.Trigger)
    tray._on_activated(QSystemTrayIcon.ActivationReason.DoubleClick)

    window.toggle_tray_visibility.assert_called_once()


def test_toggle_autostart_uses_registry_state(tmp_path, qapp, monkeypatch):
    import pet.tray as tray_module

    tray, _ = _make_tray(tmp_path, qapp, monkeypatch, enabled=False)
    calls: list[str] = []
    state = {"enabled": False}

    def enable() -> bool:
        calls.append("enable")
        state["enabled"] = True
        return True

    def disable() -> bool:
        calls.append("disable")
        state["enabled"] = False
        return True

    monkeypatch.setattr(tray_module.autostart, "is_enabled", lambda: state["enabled"])
    monkeypatch.setattr(tray_module.autostart, "enable", enable)
    monkeypatch.setattr(tray_module.autostart, "disable", disable)

    tray._toggle_autostart()
    tray._toggle_autostart()

    assert calls == ["enable", "disable"]


def test_hide_to_tray_leaves_badges_independent(qapp):
    """桌宠隐藏只收起桌宠与气泡；角标由独立开关控制，不随托盘一起隐藏。"""
    window = _bare_window()
    bubble = SpeechBubble(timeout_ms=0)
    badge = StatusBadge()
    codex_badge = StatusBadge(agent_name="Codex")
    window.bubble = bubble
    window.status_badge = badge
    window.codex_status_badge = codex_badge
    window._reposition_overlays = Mock()

    window.show()
    bubble.set_text("你好")
    badge.set_state("working")
    codex_badge.set_state("waiting")
    qapp.processEvents()
    assert bubble.isVisible() and badge.isVisible() and codex_badge.isVisible()

    window.hide_to_tray()
    qapp.processEvents()
    assert not window.isVisible()
    assert not bubble.isVisible()
    # 角标独立于桌宠：隐藏桌宠后仍保持显示
    assert badge.isVisible() and codex_badge.isVisible()

    window.toggle_tray_visibility()
    qapp.processEvents()
    assert window.isVisible() and bubble.isVisible()
    assert badge.isVisible() and codex_badge.isVisible()

    # 气泡恢复前已收起时，重新显示桌宠不应强行弹出
    bubble.hide()
    window.hide_to_tray()
    window.toggle_tray_visibility()
    qapp.processEvents()
    assert window.isVisible()
    assert not bubble.isVisible()
    assert badge.isVisible() and codex_badge.isVisible()

    bubble.close()
    badge.close()
    codex_badge.close()
    window.hide()
