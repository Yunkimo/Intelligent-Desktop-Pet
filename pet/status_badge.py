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

# 缩放基准：字号 11px、横向内边距 8px、纵向 2px、圆角 9px
_BASE_FONT_PX = 11
_BASE_PAD_X = 8
_BASE_PAD_Y = 2
_BASE_RADIUS = 9.0
MIN_SCALE = 0.6
MAX_SCALE = 2.5
_EDGE_GRAB = 6  # 距右/下边缘多少像素内算"抓边缘"


class StatusBadge(QLabel):
    """状态角标；idle 时自动隐藏。

    仿气泡做成顶层置顶浮层：作为窗口子控件时只能贴在窗口角落，桌宠靠边时会被
    遮住；独立浮层才能随桌宠方位翻到屏幕空闲一侧。

    角标接受鼠标：可拖拽到任意位置（此后自动摆位不再覆盖它），双击复位回自动
    跟随。手动位置仅本次运行有效，不持久化。
    """

    # 用户双击角标清空手动位置，请求窗口重新自动摆位
    position_reset = pyqtSignal()
    # 右键角标：携带全局坐标，由窗口弹出与桌宠一致的命令菜单
    context_menu_requested = pyqtSignal(QPoint)
    # 拖拽边缘缩放后通知窗口持久化（参数为 0.6-2.5 的缩放系数）
    scale_changed = pyqtSignal(float)

    def __init__(self, parent=None, agent_name: str = "Claude", scale: float = 1.0) -> None:
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
        self.setMouseTracking(True)
        self._fg, self._bg = _STYLES["unknown"][1:]
        self._state = "idle"
        self._user_visible = True
        self._press_pos: QPoint | None = None
        self._user_moved = False
        self._scale = self._clamp_scale(scale)
        self._resizing = False
        self._resize_origin = QPoint(0, 0)
        self._resize_start_width = 1
        self._resize_start_scale = 1.0
        self.hide()

    @property
    def scale(self) -> float:
        """当前缩放系数（1.0 为基准字号 11px）。"""
        return self._scale

    @staticmethod
    def _clamp_scale(scale: float) -> float:
        return min(MAX_SCALE, max(MIN_SCALE, round(float(scale), 2)))

    def set_scale(self, scale: float) -> None:
        """外部设置缩放（启动恢复配置时用）；重新排字号与圆角。"""
        clamped = self._clamp_scale(scale)
        if clamped == self._scale and self._state != "idle":
            return
        self._scale = clamped
        self._apply_style()

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
        self._fg, self._bg = fg, bg
        self.setText(text.replace("Claude", self.agent_name))
        self._apply_style()
        self._apply_visibility()

    def _apply_style(self) -> None:
        """按当前缩放系数生成样式并重新适配尺寸。"""
        # 四舍五入（不用 round，避免 .5 时的银行家舍入）
        font_px = max(8, int(_BASE_FONT_PX * self._scale + 0.5))
        pad_x = max(4, round(_BASE_PAD_X * self._scale))
        pad_y = max(1, round(_BASE_PAD_Y * self._scale))
        radius = max(4.0, _BASE_RADIUS * self._scale)
        self.setStyleSheet(
            f"QLabel {{ color: {self._fg}; background-color: {self._bg}; "
            f"border: 1px solid {self._fg}; border-radius: {radius:.0f}px; "
            f"padding: {pad_y}px {pad_x}px; font-size: {font_px}px; }}"
        )
        self.adjustSize()
        self.update()

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

    # ---------- 拖拽移动 / 边缘缩放 / 双击复位 ----------
    def _on_edge(self, pos) -> bool:
        """是否按在右边缘或下边缘（右下角也命中），用于缩放。"""
        return pos.x() >= self.width() - _EDGE_GRAB or pos.y() >= self.height() - _EDGE_GRAB

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() != Qt.MouseButton.LeftButton:
            return
        if self._on_edge(event.position().toPoint()):
            self._resizing = True
            self._resize_origin = event.globalPosition().toPoint()
            self._resize_start_width = max(1, self.width())
            self._resize_start_scale = self._scale
            return
        self._press_pos = event.globalPosition().toPoint()

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        if self._resizing and (event.buttons() & Qt.MouseButton.LeftButton):
            # 用全局拖拽位移算比例：宽度会随缩放变化，直接用本地坐标会自我放大
            grown = event.globalPosition().toPoint().x() - self._resize_origin.x()
            ratio = (self._resize_start_width + grown) / self._resize_start_width
            self.set_scale(self._resize_start_scale * ratio)
            self.scale_changed.emit(self._scale)
            return
        if self._press_pos is None or not (event.buttons() & Qt.MouseButton.LeftButton):
            self.setCursor(
                Qt.CursorShape.SizeFDiagCursor
                if self._on_edge(event.position().toPoint())
                else Qt.CursorShape.SizeAllCursor
            )
            return
        delta = event.globalPosition().toPoint() - self._press_pos
        if delta.manhattanLength() > 4:
            self._user_moved = True
            self.move(self._clamp_to_screen(self.pos() + delta))
            self._press_pos = event.globalPosition().toPoint()

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        if event.button() != Qt.MouseButton.LeftButton:
            return
        if self._resizing:
            self._resizing = False
            self.setCursor(
                Qt.CursorShape.SizeFDiagCursor
                if self._on_edge(event.position().toPoint())
                else Qt.CursorShape.SizeAllCursor
            )
        self._press_pos = None

    def mouseDoubleClickEvent(self, event) -> None:  # noqa: N802
        if event.button() != Qt.MouseButton.LeftButton:
            return
        self._user_moved = False
        self.position_reset.emit()

    def contextMenuEvent(self, event) -> None:  # noqa: N802
        """右键弹出命令菜单；角标本身不持有菜单，只把位置交给窗口。"""
        self.context_menu_requested.emit(event.globalPos())
        event.accept()

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
        radius = max(4.0, _BASE_RADIUS * self._scale)
        painter.drawRoundedRect(QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5), radius, radius)
        painter.end()
        super().paintEvent(event)
