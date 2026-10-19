"""Claude Code 状态角标：独立于气泡的小标签，不打断宠物自己的对话。"""

from PyQt6.QtCore import QRectF, Qt
from PyQt6.QtGui import QColor, QPainter, QPen
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
    """

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
            | Qt.WindowType.Window
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._fg, self._bg = _STYLES["unknown"][1:]
        self.hide()

    def set_state(self, state: str) -> None:
        """按状态更新文案与配色；未知状态按 unknown 显示。"""
        text, fg, bg = _STYLES.get(state, _STYLES["unknown"])
        if not text:
            self.hide()
            return
        self._fg, self._bg = fg, bg
        self.setText(text)
        self.setStyleSheet(
            f"QLabel {{ color: {fg}; background-color: {bg}; "
            f"border: 1px solid {fg}; border-radius: 9px; "
            "padding: 2px 8px; font-size: 11px; }"
        )
        self.adjustSize()
        self.show()
        self.raise_()

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
