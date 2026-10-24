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

    assert "ACCOUNT_API_KEY" in dialog._balance_label.text()
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
