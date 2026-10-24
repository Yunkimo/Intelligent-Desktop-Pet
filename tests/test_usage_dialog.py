"""用量窗口测试：三段汇总展示、余额查询成功/失败与线程收敛。"""

from datetime import datetime
from decimal import Decimal
from types import SimpleNamespace

import pytest

import pet.usage_dialog as dialog_module
from pet.balance import Balance, BalanceError
from pet.usage import UsageStore
from pet.usage_dialog import UsageDialog

_PEAK = datetime(2026, 10, 26, 10, 0)


def _settings(with_key: bool = True):
    return SimpleNamespace(
        account_api_key="sk-test" if with_key else "",
        account_base_url="https://api.deepseek.com",
        balance_timeout_seconds=2,
    )


def _usage(prompt=1000, completion=200, hit=0):
    return SimpleNamespace(
        prompt_tokens=prompt,
        completion_tokens=completion,
        prompt_cache_hit_tokens=hit,
    )


def _store(tmp_path) -> UsageStore:
    """用「现在」记账，保证窗口里的「今日」一行能命中（窗口按真实日期取今日）。"""
    now = datetime.now()
    store = UsageStore(tmp_path / "usage.json")
    store.record_usage(_usage(1000, 200, 400), "deepseek-chat", at=now)
    store.record_usage(_usage(500, 50), "unknown-model", at=now)
    return store


def _balance(total="12.34") -> Balance:
    return Balance(
        provider="DeepSeek",
        currency="CNY",
        total=Decimal(total),
        granted=Decimal("2.00"),
        topped_up=Decimal("10.34"),
        available=True,
    )


def test_usage_rows_are_rendered(tmp_path, qapp):
    dialog = UsageDialog(_settings(), _store(tmp_path))

    today = [cell.text() for cell in dialog._rows["today"]]
    assert today[0] == "2"  # 请求数
    assert today[1] == "1,500"  # 输入
    assert today[2] == "400"  # 缓存命中
    assert today[3] == "250"  # 输出
    assert today[4].startswith("¥")


def test_unpriced_tokens_are_reported(tmp_path, qapp):
    dialog = UsageDialog(_settings(), _store(tmp_path))

    assert "未计价" in dialog._unpriced_label.text()
    assert dialog._unpriced_label.isHidden() is False


def test_missing_account_key_shows_hint_and_disables_button(tmp_path, qapp):
    dialog = UsageDialog(_settings(with_key=False), UsageStore(tmp_path / "usage.json"))

    assert "未配置账户 key" in dialog._balance_label.text()
    assert dialog._refresh_button.isEnabled() is False


def test_balance_success_updates_label(tmp_path, qapp, monkeypatch):
    monkeypatch.setattr(dialog_module, "fetch_balance", lambda target, timeout: _balance())
    dialog = UsageDialog(_settings(), _store(tmp_path))

    dialog.refresh_balance()
    worker = next(iter(dialog._workers))
    assert worker.wait(3000)
    qapp.processEvents()

    text = dialog._balance_label.text()
    assert "¥12.34" in text
    assert "赠送" in text and "充值" in text
    assert "可用" in text


def test_balance_failure_shows_readable_message(tmp_path, qapp, monkeypatch):
    def boom(_target, _timeout):
        raise BalanceError("账户验证失败，请检查 ACCOUNT_API_KEY 是否正确")

    monkeypatch.setattr(dialog_module, "fetch_balance", boom)
    dialog = UsageDialog(_settings(), _store(tmp_path))

    dialog.refresh_balance()
    worker = next(iter(dialog._workers))
    assert worker.wait(3000)
    qapp.processEvents()

    assert "验证失败" in dialog._balance_label.text()


def test_shutdown_waits_for_worker(tmp_path, qapp, monkeypatch):
    monkeypatch.setattr(dialog_module, "fetch_balance", lambda target, timeout: _balance())
    dialog = UsageDialog(_settings(), _store(tmp_path))
    dialog.refresh_balance()

    dialog.shutdown(timeout_ms=3000)
    assert all(not worker.isRunning() for worker in dialog._workers)


def test_refresh_without_key_does_not_spawn_worker(tmp_path, qapp):
    dialog = UsageDialog(_settings(with_key=False), UsageStore(tmp_path / "usage.json"))

    dialog.refresh_balance()
    assert dialog._workers == set()


@pytest.mark.parametrize("value", ["0.001", "abc"])
def test_unknown_price_model_does_not_break_snapshot(tmp_path, qapp, value):
    """随手塞一个坏价目不应让窗口构造失败（这里用未知模型走同一条路径）。"""
    store = UsageStore(tmp_path / "usage.json")
    store.record_usage(_usage(10, 1), value, at=datetime.now())

    dialog = UsageDialog(_settings(), store)
    assert dialog._rows["today"][0].text() == "1"


# ---------- 窗口下方的 API Key 填写入口 ----------
def test_save_key_writes_env_and_refreshes_balance(tmp_path, qapp, monkeypatch):
    import pet.config as config

    monkeypatch.setattr(config, "BASE_DIR", tmp_path)
    settings = _settings(with_key=False)
    dialog = UsageDialog(settings, UsageStore(tmp_path / "usage.json"))
    dialog.refresh_balance = lambda: calls.append(True)
    calls: list[bool] = []

    dialog._key_input.setText("sk-user-provided-key-123")
    dialog._save_account_key()

    env = (tmp_path / ".env").read_text(encoding="utf-8")
    assert "ACCOUNT_API_KEY=sk-user-provided-key-123" in env
    assert settings.account_api_key == "sk-user-provided-key-123"
    assert dialog._key_input.text() == ""  # 保存后清空，不留明文
    assert "已保存" in dialog._key_hint.text()
    assert "sk-user-provided-key-123" not in dialog._key_hint.text()  # 只回显头尾
    assert dialog._refresh_button.isEnabled() is True
    assert calls == [True]


def test_save_key_with_empty_input_only_hints(tmp_path, qapp, monkeypatch):
    import pet.config as config

    monkeypatch.setattr(config, "BASE_DIR", tmp_path)
    dialog = UsageDialog(_settings(with_key=False), UsageStore(tmp_path / "usage.json"))

    dialog._save_account_key()

    assert "请先填入" in dialog._key_hint.text()
    assert not (tmp_path / ".env").exists()


def test_key_hint_shows_masked_key_when_configured(tmp_path, qapp):
    settings = _settings(with_key=True)
    settings.account_api_key = "sk-abcdefghijklmnop"
    dialog = UsageDialog(settings, UsageStore(tmp_path / "usage.json"))

    assert "已配置" in dialog._key_hint.text()
    assert "sk-abcdefghijklmnop" not in dialog._key_hint.text()


def test_missing_key_hint_points_to_the_entry_below(tmp_path, qapp):
    dialog = UsageDialog(_settings(with_key=False), UsageStore(tmp_path / "usage.json"))

    assert "下方" in dialog._balance_label.text()
