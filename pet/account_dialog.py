"""后端账号配置窗口：网络在 QThread 执行，关闭时等待结果处理结束。"""

from PyQt6.QtCore import QThread, pyqtSignal
from PyQt6.QtWidgets import QDialog, QLabel, QLineEdit, QPushButton, QVBoxLayout

from .backend_client import BackendClient, BackendError


class AccountWorker(QThread):
    ready = pyqtSignal(object)
    failed = pyqtSignal(str)

    def __init__(self, backend, operation, code="", parent=None):
        super().__init__(parent)
        self.backend, self.operation, self.code = backend, operation, code

    def run(self):
        try:
            result = (
                self.backend.device_login(self.code)
                if self.operation == "login"
                else self.backend.logout()
            )
            self.ready.emit(result)
        except BackendError as exc:
            self.failed.emit(str(exc))
        except Exception:
            self.failed.emit("账号操作失败，请重试")


class AccountDialog(QDialog):
    changed = pyqtSignal(object)

    def __init__(self, backend, store, parent=None):
        super().__init__(parent)
        self.backend, self.store = backend, store
        self.worker = None
        self.setWindowTitle("后端账号")
        layout = QVBoxLayout(self)
        self.status = QLabel("从小程序取得配对码后绑定私人账号；API Key 登录使用默认演示账号。")
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.code = QLineEdit()
        self.code.setEchoMode(QLineEdit.EchoMode.Password)
        self.code.setPlaceholderText("粘贴一次性配对码")
        layout.addWidget(self.code)
        self.buttons = []
        for title, operation in (
            ("配对绑定", "pair"),
            ("API Key 登录演示账号", "demo"),
            ("退出并清除本机账号", "logout"),
        ):
            button = QPushButton(title)
            button.clicked.connect(lambda _checked=False, op=operation: self.start(op))
            layout.addWidget(button)
            self.buttons.append(button)

    def start(self, operation):
        code = self.code.text().strip()
        if operation == "pair" and not code:
            self.status.setText("请先输入配对码")
            return
        # 使用快照，登录失败不改变当前账号。
        client = BackendClient(self.backend.base_url, self.backend._token)
        client.session_token = self.backend.session_token
        if operation == "logout":
            try:
                self.store.clear()
            except OSError:
                self.status.setText("无法清除账号文件，请检查 data 目录权限")
                return
            self.changed.emit(None)
        self.worker = AccountWorker(
            client,
            "logout" if operation == "logout" else "login",
            code if operation == "pair" else "",
            self,
        )
        self.worker.ready.connect(lambda value: self.complete(value, operation))
        self.worker.failed.connect(self.status.setText)
        self.worker.finished.connect(self.finished_work)
        for button in self.buttons:
            button.setEnabled(False)
        self.status.setText("正在处理…")
        self.worker.start()

    def complete(self, result, operation):
        if operation == "logout":
            self.status.setText("本机账号已清除")
            return
        try:
            self.store.save(result)
        except OSError:
            self.status.setText("无法保存本机账号，请检查 data 目录权限后重新绑定")
            return
        self.code.clear()
        self.changed.emit(result)
        self.status.setText(f"已绑定用户 {result['user_id']}")

    def finished_work(self):
        for button in self.buttons:
            button.setEnabled(True)

    def reject(self):
        if self.worker is None or not self.worker.isRunning():
            super().reject()

    def closeEvent(self, event):
        if self.worker is not None and self.worker.isRunning():
            event.ignore()
        else:
            super().closeEvent(event)
