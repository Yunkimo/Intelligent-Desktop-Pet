"""输入框 + 麦克风按钮。"""

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import QHBoxLayout, QLineEdit, QToolButton, QWidget


class ChatInput(QWidget):
    submitted = pyqtSignal(str)  # 文字提交
    mic_toggled = pyqtSignal(bool)  # 麦克风开始/停止（True=开始录音）

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        self.edit = QLineEdit()
        self.edit.setPlaceholderText("说点什么吧…")
        self.edit.returnPressed.connect(self._on_submit)

        self.mic = QToolButton()
        self.mic.setText("🎤")
        self.mic.setCheckable(True)
        self.mic.setToolTip("按住说话")
        self.mic.toggled.connect(self.mic_toggled.emit)

        layout.addWidget(self.edit, 1)
        layout.addWidget(self.mic)
        self.setFixedWidth(300)
        self.setFixedHeight(36)

    def _on_submit(self) -> None:
        text = self.edit.text().strip()
        if text:
            self.submitted.emit(text)
            self.edit.clear()

    def set_listening(self, listening: bool) -> None:
        self.mic.blockSignals(True)
        self.mic.setChecked(listening)
        self.mic.blockSignals(False)
        if listening:
            self.mic.setText("⏹")
            self.edit.setPlaceholderText("聆听中…")
        else:
            self.mic.setText("🎤")
            self.edit.setPlaceholderText("说点什么吧…")

    def set_busy(self, busy: bool) -> None:
        self.edit.setEnabled(not busy)
        self.mic.setEnabled(not busy)

    def focus_input(self) -> None:
        self.edit.setFocus(Qt.FocusReason.MouseFocusReason)
