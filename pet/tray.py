"""系统托盘：左键显隐桌宠，右键复用 A5 命令表。"""

from typing import TYPE_CHECKING

from PyQt6.QtCore import QObject, Qt
from PyQt6.QtGui import QIcon, QPixmap
from PyQt6.QtWidgets import QMenu, QSystemTrayIcon

from . import autostart
from .commands import Command, populate_menu
from .config import Settings

if TYPE_CHECKING:
    from .window import PetWindow

_ICON_SIZES = (16, 24, 32, 48, 64)


def _build_icon(settings: Settings) -> QIcon:
    """把当前形象缩成多档尺寸的托盘图标；无形象或加载失败时返回空图标。"""
    if not settings.frames:
        return QIcon()
    source = QPixmap(str(settings.assets_dir / settings.frames[0]))
    if source.isNull():
        return QIcon()
    icon = QIcon()
    for size in _ICON_SIZES:
        icon.addPixmap(
            source.scaled(
                size,
                size,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        )
    return icon


class TrayIcon(QObject):
    """托盘图标：左键显隐桌宠，右键弹出与桌宠右键一致的命令表。"""

    def __init__(
        self, window: "PetWindow", settings: Settings, parent: QObject | None = None
    ) -> None:
        super().__init__(parent)
        self._window = window
        self._icon = QSystemTrayIcon(_build_icon(settings), self)
        self._icon.setToolTip(f"{settings.pet_name}：左键显示/隐藏，右键菜单")
        # 勾选态在 populate 时求值，菜单每次弹出前清空重建才能反映最新状态
        self._menu = QMenu()
        self._menu.aboutToShow.connect(self._rebuild_menu)
        self._icon.setContextMenu(self._menu)
        self._icon.activated.connect(self._on_activated)
        self._icon.show()

    def hide(self) -> None:
        """移除托盘图标（退出时调用）。"""
        self._icon.hide()

    def _on_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        """左键单击切换桌宠显隐；双击在 Windows 上也会触发一次单击，不重复处理。"""
        if reason == QSystemTrayIcon.ActivationReason.Trigger:
            self._window.toggle_tray_visibility()

    def _rebuild_menu(self) -> None:
        """复用桌宠右键命令表，追加开机自启勾选项，「退出」固定在菜单最下方。"""
        self._menu.clear()
        commands = self._window._build_commands(include_hide_to_tray=False, include_quit=False)
        commands.append(
            Command(
                "开机自启动",
                self._toggle_autostart,
                checkable=True,
                checked=autostart.is_enabled,
            )
        )
        # 「退出」压轴：Windows 用户的习惯位置，也避免误点后与自启勾选混在一起
        commands.append(self._window._quit_command())
        populate_menu(self._menu, commands)

    def _toggle_autostart(self) -> None:
        """按注册表当前状态切换开机自启；注册表是唯一事实源。"""
        if autostart.is_enabled():
            ok = autostart.disable()
        else:
            ok = autostart.enable()
        if not ok:
            self._icon.showMessage("开机自启", "设置失败，请检查系统权限或注册表")
