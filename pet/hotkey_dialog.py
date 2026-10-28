"""设置语音快捷键对话框：点击捕获区后按下组合键即捕获。"""

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QDialog, QDialogButtonBox, QLabel, QVBoxLayout


class _KeyCapture(QLabel):
    """只用来捕获按键的标签：记录「修饰键 + 主键」组合。"""

    def __init__(self, text: str = "", parent=None) -> None:
        super().__init__(text, parent)
        self.hotkey = ""
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setFixedHeight(40)
        self.setStyleSheet("border: 1px solid gray; border-radius: 4px; padding: 4px;")

    def keyPressEvent(self, event) -> None:  # noqa: N802
        parts = []
        mods = event.modifiers()
        if mods & Qt.KeyboardModifier.ControlModifier:
            parts.append("ctrl")
        if mods & Qt.KeyboardModifier.ShiftModifier:
            parts.append("shift")
        if mods & Qt.KeyboardModifier.AltModifier:
            parts.append("alt")

        name = self._key_name(event.key())
        if name is None:
            return  # 纯修饰键或无法识别的键，忽略
        parts.append(name)
        self.hotkey = "+".join(parts)
        self.setText(self.hotkey)

    @staticmethod
    def _key_name(key: int) -> str | None:
        """把 Qt 键码映射成与 pet.hotkey.parse_hotkey 兼容的按键名。"""
        special = {
            Qt.Key.Key_Space: "space",
            Qt.Key.Key_Return: "enter",
            Qt.Key.Key_Enter: "enter",
            Qt.Key.Key_Tab: "tab",
            Qt.Key.Key_Backspace: "backspace",
            Qt.Key.Key_Delete: "delete",
            Qt.Key.Key_Escape: "esc",
            Qt.Key.Key_Up: "up",
            Qt.Key.Key_Down: "down",
            Qt.Key.Key_Left: "left",
            Qt.Key.Key_Right: "right",
            Qt.Key.Key_Home: "home",
            Qt.Key.Key_End: "end",
            Qt.Key.Key_PageUp: "page_up",
            Qt.Key.Key_PageDown: "page_down",
            Qt.Key.Key_Insert: "insert",
            Qt.Key.Key_CapsLock: "caps_lock",
        }
        for i in range(1, 25):
            special[getattr(Qt.Key, f"Key_F{i}")] = f"f{i}"

        if key in special:
            return special[key]
        # 可见可打印 ASCII（含反引号 ` 等符号键）
        if 0x21 <= key <= 0x7E:
            return chr(key).lower()
        return None


class HotkeyDialog(QDialog):
    """选择全局语音快捷键：点击捕获区并按下组合键，保存后写回配置。"""

    def __init__(self, current: str, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("设置语音快捷键")
        self.setMinimumWidth(340)
        self.hotkey = ""
        self._current = current

        hint = QLabel(
            "长按快捷键说话，松开后自动识别。\n"
            "点击下方区域，再按下你想要的组合键（可含 Ctrl/Shift/Alt）。"
        )
        hint.setWordWrap(True)

        self.capture = _KeyCapture(f"当前：{current}")
        self.capture.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("保存")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("取消")
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addWidget(hint)
        layout.addWidget(self.capture)
        layout.addWidget(buttons)

        self.capture.setFocus()

    def _on_accept(self) -> None:
        self.hotkey = self.capture.hotkey or self._current
        self.accept()
