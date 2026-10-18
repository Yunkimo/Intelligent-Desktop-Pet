"""Claude Code 状态角标：独立于气泡的小标签，不打断宠物自己的对话。"""

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QLabel

_STYLES = {
    "working": ("Claude 处理中…", "#1f6feb", "#e8f0fe"),
    "waiting": ("Claude 等你确认", "#9a6700", "#fff8c5"),
    "done": ("Claude 本轮完成", "#1a7f37", "#dafbe1"),
    "unknown": ("Claude 状态未知", "#57606a", "#f6f8fa"),
    "idle": ("", "", ""),
}


class StatusBadge(QLabel):
    """右上角状态角标；idle 时自动隐藏。"""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.hide()

    def set_state(self, state: str) -> None:
        """按状态更新文案与配色；未知状态按 unknown 显示。"""
        text, fg, bg = _STYLES.get(state, _STYLES["unknown"])
        if not text:
            self.hide()
            return
        self.setText(text)
        self.setStyleSheet(
            f"QLabel {{ color: {fg}; background-color: {bg}; "
            f"border: 1px solid {fg}; border-radius: 9px; "
            "padding: 2px 8px; font-size: 11px; }}"
        )
        self.adjustSize()
        self.show()
        self.raise_()
