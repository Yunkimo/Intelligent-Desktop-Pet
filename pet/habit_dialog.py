"""生活习惯窗口：查看、手动添加、删除与清空长期偏好。

习惯存在本地 data/habits.json（明文），本窗口是唯一的查看与清理入口；
改动后由调用方刷新系统提示词，让新习惯立即生效。
"""

from PyQt6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QPushButton,
    QVBoxLayout,
)

from .habits import MAX_TEXT_LENGTH, HabitStore


class HabitDialog(QDialog):
    """习惯列表 + 添加 + 删除 + 清空。"""

    def __init__(self, store: HabitStore, parent=None) -> None:
        super().__init__(parent)
        self._store = store
        self.setWindowTitle("生活习惯")
        self.setMinimumWidth(420)
        self._build_ui()
        self._refresh()

    # ---------- 界面 ----------
    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)

        hint = QLabel("桌宠会记住这些长期偏好，并在对话时参考。只存在本机，可随时删除。")
        hint.setWordWrap(True)
        hint.setStyleSheet("color: #666; font-size: 11px;")
        layout.addWidget(hint)

        self._list = QListWidget()
        layout.addWidget(self._list)

        add_row = QHBoxLayout()
        self._input = QLineEdit()
        self._input.setPlaceholderText(f"例如：每天 8 点起床（{MAX_TEXT_LENGTH} 字以内）")
        self._input.returnPressed.connect(self._add_habit)
        self._add_button = QPushButton("添加")
        self._add_button.clicked.connect(self._add_habit)
        add_row.addWidget(self._input, 1)
        add_row.addWidget(self._add_button, 0)
        layout.addLayout(add_row)

        self._status = QLabel("")
        self._status.setStyleSheet("color: #777; font-size: 11px;")
        layout.addWidget(self._status)

        action_row = QHBoxLayout()
        self._delete_button = QPushButton("删除选中")
        self._delete_button.clicked.connect(self._delete_selected)
        self._clear_button = QPushButton("全部清空")
        self._clear_button.clicked.connect(self._clear_all)
        action_row.addWidget(self._delete_button)
        action_row.addWidget(self._clear_button)
        action_row.addStretch(1)
        layout.addLayout(action_row)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.button(QDialogButtonBox.StandardButton.Close).setText("关闭")
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    # ---------- 行为 ----------
    def _refresh(self) -> None:
        self._list.clear()
        habits = self._store.list_habits()
        for item in habits:
            self._list.addItem(f"{item['text']}    ({item['created_at']})")
        self._list.setEnabled(bool(habits))
        self._delete_button.setEnabled(bool(habits))
        self._clear_button.setEnabled(bool(habits))
        if self._store.load_error:
            self._status.setText(self._store.load_error)

    def _add_habit(self) -> None:
        ok, message = self._store.add(self._input.text())
        if ok:
            self._input.clear()
            self._status.setText(f"已记住：{message}")
        else:
            self._status.setText(f"没记成：{message}")
        self._refresh()

    def _delete_selected(self) -> None:
        row = self._list.currentRow()
        habits = self._store.list_habits()
        if 0 <= row < len(habits):
            self._store.remove(habits[row]["id"])
            self._status.setText("已删除一条")
            self._refresh()

    def _clear_all(self) -> None:
        removed = self._store.clear()
        self._status.setText(f"已清空 {removed} 条" if removed else "本来就没有记录")
        self._refresh()
