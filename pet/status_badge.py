"""Claude Code 状态角标：独立于气泡的小标签，不打断宠物自己的对话。"""

from PyQt6.QtCore import QPoint, QRectF, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QGuiApplication, QPainter, QPen
from PyQt6.QtWidgets import QLabel

_STYLES = {
    "working": ("Claude 处理中…", "#1f6feb", "#e8f0fe"),
    "waiting": ("Claude 等你确认", "#9a6700", "#fff8c5"),
    "done": ("Claude 本轮完成", "#1a7f37", "#dafbe1"),
    "unknown": ("Claude 状态未知", "#57606a", "#f6f8fa"),
    "idle": ("", "", ""),
}


class StatusBadge(QLabel):
    """状态角标；idle 时自动隐藏。

    仿气泡做成顶层置顶浮层：作为窗口子控件时只能贴在窗口角落，桌宠靠边时会被
    遮住；独立浮层才能随桌宠方位翻到屏幕空闲一侧。

    角标接受鼠标：可拖拽到任意位置（此后自动摆位不再覆盖它），双击复位回自动
    跟随。手动位置仅本次运行有效，不持久化。
    """

    # 用户双击角标清空手动位置，请求窗口重新自动摆位
    position_reset = pyqtSignal()

    def __init__(self, parent=None, agent_name: str = "Claude") -> None:
        super().__init__(parent)
        self.agent_name = agent_name
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
            | Qt.WindowType.Window
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setCursor(Qt.CursorShape.SizeAllCursor)
        self._fg, self._bg = _STYLES["unknown"][1:]
        self._state = "idle"
        self._user_visible = True
        self._press_pos: QPoint | None = None
        self._user_moved = False
        self.hide()

    @property
    def is_manually_positioned(self) -> bool:
        """用户是否已手动拖拽过角标；为真时自动摆位不再覆盖其位置。"""
        return self._user_moved

    def set_state(self, state: str) -> None:
        """按状态更新文案与配色；未知状态按 unknown 显示。"""
        text, fg, bg = _STYLES.get(state, _STYLES["unknown"])
        self._state = state if text else "idle"
        if not text:
            self.hide()
            return
        text = text.replace("Claude", self.agent_name)
        self._fg, self._bg = fg, bg
        self.setText(text)
        self.setStyleSheet(
            f"QLabel {{ color: {fg}; background-color: {bg}; "
            f"border: 1px solid {fg}; border-radius: 9px; "
            "padding: 2px 8px; font-size: 11px; }"
        )
        self.adjustSize()
        self._apply_visibility()

    def set_user_visible(self, visible: bool) -> None:
        """用户级显隐开关：关闭后状态更新也不弹出，重开时按当前状态恢复。"""
        self._user_visible = bool(visible)
        self._apply_visibility()

    def _apply_visibility(self) -> None:
        """用户开关与当前状态都允许时才显示。"""
        if not self._user_visible or self._state == "idle":
            self.hide()
            return
        self.show()
        self.raise_()

    # ---------- 拖拽移动与双击复位 ----------
    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() != Qt.MouseButton.LeftButton:
            return
        self._press_pos = event.globalPosition().toPoint()

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        if self._press_pos is None or not (event.buttons() & Qt.MouseButton.LeftButton):
            return
        delta = event.globalPosition().toPoint() - self._press_pos
        if delta.manhattanLength() > 4:
            self._user_moved = True
            self.move(self._clamp_to_screen(self.pos() + delta))
            self._press_pos = event.globalPosition().toPoint()

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        if event.button() != Qt.MouseButton.LeftButton:
            return
        self._press_pos = None

    def mouseDoubleClickEvent(self, event) -> None:  # noqa: N802
        if event.button() != Qt.MouseButton.LeftButton:
            return
        self._user_moved = False
        self.position_reset.emit()

    def _clamp_to_screen(self, pos: QPoint) -> QPoint:
        """把角标位置夹在可用区域内，避免拖出屏幕后无法再双击复位。"""
        screen = self.screen() or QGuiApplication.primaryScreen()
        geo = screen.availableGeometry() if screen else None
        if geo is None:
            return pos
        x = max(geo.left(), min(pos.x(), geo.right() - self.width() + 1))
        y = max(geo.top(), min(pos.y(), geo.bottom() - self.height() + 1))
        return QPoint(x, y)

    def paintEvent(self, event) -> None:  # noqa: N802
        """自行绘制圆角底色与边框。

        角标是半透明顶层窗口，样式表里的 background/border 不会生效，只能由
        paintEvent 画出胶囊底；文字仍交给 QLabel 按样式表绘制。
        """
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(QPen(QColor(self._fg), 1))
        painter.setBrush(QColor(self._bg))
        painter.drawRoundedRect(QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5), 9, 9)
        painter.end()
        super().paintEvent(event)
