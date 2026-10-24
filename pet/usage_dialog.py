"""Token 用量窗口：本地记账汇总 + 账户余额查询。

本地三段汇总直接读 UsageStore 的快照；账户余额需要联网，放在 BalanceWorker 里跑，
不占用 UI 线程。窗口本身不创建线程的生命周期依赖：worker 的 parent 是桌宠窗口，
对话框关闭只请求取消，避免线程还活着时对话框先被销毁。
"""

import threading
from decimal import Decimal

from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
)

from .balance import Balance, BalanceError, BalanceTarget, fetch_balance
from .config import save_env_values
from .pricing import PRICE_AS_OF
from .usage import Totals, UsageStore

_PERIODS = (
    ("today", "今日"),
    ("last_7_days", "近 7 天"),
    ("total", "总计"),
)
_HEADERS = ("请求数", "输入", "缓存命中", "输出", "估算费用")
_FOOTNOTE = (
    "费用按 DeepSeek 官方价目估算（价格表更新于 {date}）：空闲价为高峰价的一半，"
    "高峰为北京时间工作日 9:00-12:00、14:00-18:00；法定节假日与调休未建模，节假日会高估。"
    "余额为账户级数据，口径与本地记账不同，均不代表官方账单。"
)


class BalanceWorker(QThread):
    """后台查一次余额；失败只回可读文案，不携带任何请求头内容。"""

    ready = pyqtSignal(object)
    failed = pyqtSignal(str)

    def __init__(self, target: BalanceTarget, timeout: float, parent=None) -> None:
        super().__init__(parent)
        self._target = target
        self._timeout = timeout
        self._cancelled = threading.Event()

    def request_stop(self) -> None:
        """请求放弃结果；网络请求由超时上限兜底，不在 UI 线程阻塞等待。"""
        self._cancelled.set()

    def run(self) -> None:
        try:
            result = fetch_balance(self._target, self._timeout)
        except BalanceError as exc:
            if not self._cancelled.is_set():
                self.failed.emit(str(exc))
            return
        except Exception:  # noqa: BLE001 - 后台线程不向 UI 抛未捕获异常
            if not self._cancelled.is_set():
                self.failed.emit("余额查询失败")
            return
        if not self._cancelled.is_set():
            self.ready.emit(result)


def _fmt_int(value: int) -> str:
    return f"{value:,}"


def _fmt_money(value: Decimal) -> str:
    return f"¥{value:.4f}"


def _mask_key(key: str) -> str:
    """密钥只回显头尾，避免整串明文出现在界面上或截图里。"""
    if len(key) <= 10:
        return "已保存"
    return f"{key[:6]}…{key[-4:]}"


def _normalize_base_url(text: str) -> str:
    """接口地址留空返回空串；没写协议时补 https，尾斜杠去掉。"""
    value = text.strip().rstrip("/")
    if not value:
        return ""
    return value if "://" in value else f"https://{value}"


class UsageDialog(QDialog):
    """展示用量与余额；构造不产生网络副作用，首次查询在 showEvent 触发。"""

    # 接推理用的 key 或地址变了，窗口据此重建 LLM 客户端
    llm_config_changed = pyqtSignal()

    def __init__(self, settings, store: UsageStore, parent=None) -> None:
        super().__init__(parent)
        self._settings = settings
        self._store = store
        self._workers: set[BalanceWorker] = set()
        self._balance_requested = False
        self.setWindowTitle("Token 用量")
        self.setMinimumWidth(470)
        self._build_ui()
        self._refresh_usage()

    # ---------- 界面 ----------
    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)

        usage_box = QGroupBox("桌宠本地用量")
        self._grid = QGridLayout(usage_box)
        for column, title in enumerate(("", *_HEADERS)):
            label = QLabel(title)
            label.setStyleSheet("color: #666;")
            self._grid.addWidget(label, 0, column)
        self._rows: dict[str, list[QLabel]] = {}
        for row, (key, title) in enumerate(_PERIODS, start=1):
            self._grid.addWidget(QLabel(title), row, 0)
            cells = [QLabel("—") for _ in _HEADERS]
            for column, cell in enumerate(cells, start=1):
                cell.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                self._grid.addWidget(cell, row, column)
            self._rows[key] = cells
        self._unpriced_label = QLabel("")
        self._unpriced_label.setStyleSheet("color: #a15c00;")
        self._unpriced_label.hide()
        self._grid.addWidget(self._unpriced_label, len(_PERIODS) + 1, 0, 1, len(_HEADERS) + 1)
        layout.addWidget(usage_box)

        balance_box = QGroupBox("账户余额")
        balance_layout = QHBoxLayout(balance_box)
        self._balance_label = QLabel("")
        self._balance_label.setWordWrap(True)
        self._refresh_button = QPushButton("刷新余额")
        self._refresh_button.clicked.connect(self.refresh_balance)
        balance_layout.addWidget(self._balance_label, 1)
        balance_layout.addWidget(self._refresh_button, 0)
        layout.addWidget(balance_box)

        layout.addWidget(self._build_key_box())

        footnote = QLabel(_FOOTNOTE.format(date=PRICE_AS_OF.isoformat()))
        footnote.setWordWrap(True)
        footnote.setStyleSheet("color: #777; font-size: 11px;")
        layout.addWidget(footnote)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.button(QDialogButtonBox.StandardButton.Close).setText("关闭")
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self._apply_initial_balance_hint()

    def _build_key_box(self) -> QGroupBox:
        """窗口下方的 API 配置入口：新用户不碰 .env 也能接入自己的 API。"""
        box = QGroupBox("配置 API")
        grid = QGridLayout(box)

        self._llm_key_input = self._secret_input("桌宠对话用，必填即接入")
        self._base_url_input = QLineEdit()
        current_url = getattr(self._settings, "llm_base_url", "") or "默认地址"
        self._base_url_input.setPlaceholderText(f"留空沿用 {current_url}")
        self._account_key_input = self._secret_input("可留空，默认沿用上面的 Key")

        self._key_save = QPushButton("保存")
        self._key_save.clicked.connect(self._save_api_config)
        for entry in (self._llm_key_input, self._base_url_input, self._account_key_input):
            entry.returnPressed.connect(self._save_api_config)

        self._key_hint = QLabel("")
        self._key_hint.setWordWrap(True)
        self._key_hint.setStyleSheet("color: #777; font-size: 11px;")

        grid.addWidget(QLabel("API Key"), 0, 0)
        grid.addWidget(self._llm_key_input, 0, 1)
        grid.addWidget(self._key_save, 0, 2, 3, 1)
        grid.addWidget(QLabel("API 地址"), 1, 0)
        grid.addWidget(self._base_url_input, 1, 1)
        grid.addWidget(QLabel("账户查询 Key"), 2, 0)
        grid.addWidget(self._account_key_input, 2, 1)
        grid.addWidget(self._key_hint, 3, 0, 1, 3)
        self._refresh_key_hint()
        return box

    @staticmethod
    def _secret_input(placeholder: str) -> QLineEdit:
        entry = QLineEdit()
        entry.setEchoMode(QLineEdit.EchoMode.Password)
        entry.setPlaceholderText(placeholder)
        return entry

    def _refresh_key_hint(self) -> None:
        llm_key = getattr(self._settings, "llm_api_key", "")
        account_key = getattr(self._settings, "account_api_key", "")
        if llm_key:
            text = f"已接入 {_mask_key(llm_key)}"
            text += (
                f"，账户查询用 {_mask_key(account_key)}"
                if account_key
                else "，账户查询沿用同一把 key"
            )
        else:
            text = "还没配置？粘贴自己的 API Key 保存即可"
        self._key_hint.setText(text + "；只写入本机 .env，不会提交到仓库")

    def _save_api_config(self) -> None:
        """把填写的项写入 .env 并立即生效；留空的项保持不变，明文不回填。"""
        llm_key = self._llm_key_input.text().strip()
        base_url = _normalize_base_url(self._base_url_input.text())
        account_key = self._account_key_input.text().strip()
        if not any((llm_key, base_url, account_key)):
            self._key_hint.setText("请至少填写一项再保存")
            return

        values: dict[str, str] = {}
        if llm_key:
            values["LLM_API_KEY"] = llm_key
        if base_url:
            values["LLM_BASE_URL"] = base_url
        if account_key:
            values["ACCOUNT_API_KEY"] = account_key
        try:
            save_env_values(**values)
        except OSError as exc:
            self._key_hint.setText(f"保存失败：{exc}")
            return

        old_base_url = getattr(self._settings, "llm_base_url", "")
        llm_changed = bool(llm_key or base_url)
        if llm_key:
            self._settings.llm_api_key = llm_key
            if not account_key:
                # 账户 key 留空时按 .env 的回退规则沿用推理 key
                self._settings.account_api_key = llm_key
        if base_url:
            self._settings.llm_base_url = base_url
            if self._settings.account_base_url == old_base_url:
                self._settings.account_base_url = base_url
        if account_key:
            self._settings.account_api_key = account_key

        for entry in (self._llm_key_input, self._base_url_input, self._account_key_input):
            entry.clear()
        self._refresh_key_hint()
        if llm_changed:
            self.llm_config_changed.emit()
        has_key = bool(getattr(self._settings, "account_api_key", ""))
        self._refresh_button.setEnabled(has_key)
        if has_key:
            self._balance_label.setText("已更新配置，正在查询账户余额…")
            self.refresh_balance()

    def _apply_initial_balance_hint(self) -> None:
        if not getattr(self._settings, "account_api_key", ""):
            self._balance_label.setText("未配置 API Key：在下方填入自己的 Key 即可查询余额")
            self._refresh_button.setEnabled(False)
        else:
            self._balance_label.setText("尚未查询，点击右侧按钮获取账户余额")

    # ---------- 本地用量 ----------
    def _refresh_usage(self) -> None:
        snapshot = self._store.snapshot()
        for key, _title in _PERIODS:
            totals: Totals = snapshot[key]
            values = (
                _fmt_int(totals.requests),
                _fmt_int(totals.prompt),
                _fmt_int(totals.cached),
                _fmt_int(totals.completion),
                _fmt_money(totals.cost_cny),
            )
            for cell, text in zip(self._rows[key], values):
                cell.setText(text)
        notices = []
        if snapshot["load_error"]:
            notices.append(snapshot["load_error"])
        unpriced = snapshot["total"].unpriced
        if unpriced:
            notices.append(f"另有 {_fmt_int(unpriced)} token 因模型未收录价目未计价")
        if notices:
            self._unpriced_label.setText("；".join(notices))
            self._unpriced_label.show()
        else:
            self._unpriced_label.hide()

    # ---------- 账户余额 ----------
    def refresh_balance(self) -> None:
        if not self._settings.account_api_key:
            self._apply_initial_balance_hint()
            return
        for worker in self._workers:
            if worker.isRunning():
                return  # 同一时刻只允许一个查询
        target = BalanceTarget(
            api_key=self._settings.account_api_key,
            base_url=self._settings.account_base_url,
        )
        worker = BalanceWorker(target, self._settings.balance_timeout_seconds, parent=self.parent())
        worker.ready.connect(self._on_balance_ready)
        worker.failed.connect(self._on_balance_failed)
        worker.finished.connect(lambda w=worker: self._release_worker(w))
        self._workers.add(worker)
        self._balance_requested = True
        self._balance_label.setText("正在查询账户余额…")
        self._refresh_button.setEnabled(False)
        worker.start()

    def _release_worker(self, worker: BalanceWorker) -> None:
        """线程结束后移出注册表并交给 Qt 回收，保证运行期间始终有 Python 引用。"""
        self._workers.discard(worker)
        worker.deleteLater()
        self._refresh_button.setEnabled(bool(self._settings.account_api_key))

    def _on_balance_ready(self, balance: Balance) -> None:
        spare = []
        if balance.granted is not None:
            spare.append(f"赠送 ¥{balance.granted:.2f}")
        if balance.topped_up is not None:
            spare.append(f"充值 ¥{balance.topped_up:.2f}")
        suffix = f"（{'、'.join(spare)}）" if spare else ""
        state = "可用" if balance.available else "不可用"
        text = (
            f"{balance.provider} 账户余额 ¥{balance.total:.2f} {balance.currency}{suffix}，{state}"
        )
        self._balance_label.setText(text)

    def _on_balance_failed(self, message: str) -> None:
        self._balance_label.setText(message)

    # ---------- 生命周期 ----------
    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        if not self._balance_requested:
            self.refresh_balance()

    def closeEvent(self, event) -> None:  # noqa: N802
        self._cancel_workers()
        super().closeEvent(event)

    def done(self, result: int) -> None:  # noqa: N802
        self._cancel_workers()
        super().done(result)

    def _cancel_workers(self) -> None:
        """只请求停止，不阻塞等待：worker 受网络超时约束自行结束。"""
        for worker in list(self._workers):
            worker.request_stop()

    def shutdown(self, timeout_ms: int = 1500) -> None:
        """应用退出时调用：先请求取消，再有限等待，防止线程随进程一起销毁。"""
        self._cancel_workers()
        for worker in list(self._workers):
            worker.wait(timeout_ms)
