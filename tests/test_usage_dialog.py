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
        llm_api_key="sk-llm-key-123456" if with_key else "",  # pragma: allowlist secret -- 测试假值
        llm_base_url="https://api.deepseek.com",
        account_api_key="sk-test" if with_key else "",  # pragma: allowlist secret -- 测试假值
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
    now = datetime.now().astimezone()
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

    assert "未配置 API Key" in dialog._balance_label.text()
    assert dialog._refresh_button.isEnabled() is False


def test_balance_fields_show_all_details(tmp_path, qapp, monkeypatch):
    monkeypatch.setattr(dialog_module, "fetch_balance", lambda target, timeout: _balance())
    dialog = UsageDialog(_settings(), _store(tmp_path))

    dialog.refresh_balance()
    worker = next(iter(dialog._workers))
    assert worker.wait(3000)
    qapp.processEvents()

    fields = dialog._balance_fields
    assert fields["provider"].text() == "DeepSeek"
    assert fields["currency"].text() == "CNY"
    assert fields["total"].text() == "¥12.34"
    assert fields["breakdown"].text() == "赠送 ¥2.00 · 充值 ¥10.34"
    assert fields["status"].text() == "可用"
    assert fields["checked_at"].text()  # 查询时间已填
    assert "已更新" in dialog._balance_label.text()


def test_balance_fields_default_to_placeholder(tmp_path, qapp):
    dialog = UsageDialog(_settings(), UsageStore(tmp_path / "usage.json"))

    for key, field in dialog._balance_fields.items():
        assert field.text() == "—", key


def test_balance_unavailable_is_flagged(tmp_path, qapp, monkeypatch):
    empty = Balance(
        provider="DeepSeek",
        currency="CNY",
        total=Decimal("0"),
        granted=Decimal("0"),
        topped_up=Decimal("0"),
        available=False,
    )
    monkeypatch.setattr(dialog_module, "fetch_balance", lambda target, timeout: empty)
    dialog = UsageDialog(_settings(), _store(tmp_path))

    dialog.refresh_balance()
    worker = next(iter(dialog._workers))
    assert worker.wait(3000)
    qapp.processEvents()

    assert dialog._balance_fields["status"].text() == "不可用"
    assert "#c0392b" in dialog._balance_fields["status"].styleSheet()
    assert "余额不足" in dialog._balance_label.text()


def test_balance_failure_keeps_previous_values(tmp_path, qapp, monkeypatch):
    """先成功再失败：数值不能被抹成「—」，否则会让人以为查不到。"""
    monkeypatch.setattr(dialog_module, "fetch_balance", lambda target, timeout: _balance())
    dialog = UsageDialog(_settings(), _store(tmp_path))
    dialog.refresh_balance()
    assert next(iter(dialog._workers)).wait(3000)
    qapp.processEvents()

    def boom(_target, _timeout):
        raise BalanceError("余额查询超时，请检查网络后重试")

    monkeypatch.setattr(dialog_module, "fetch_balance", boom)
    dialog.refresh_balance()
    assert next(iter(dialog._workers)).wait(3000)
    qapp.processEvents()

    assert dialog._balance_fields["total"].text() == "¥12.34"
    assert "超时" in dialog._balance_label.text()


def test_balance_note_explains_missing_usage_api(tmp_path, qapp, monkeypatch):
    monkeypatch.setattr(dialog_module, "fetch_balance", lambda target, timeout: _balance())
    dialog = UsageDialog(_settings(), _store(tmp_path))

    note = dialog._usage_note.text()
    assert "未提供账户用量查询接口" in note
    assert "上方" in note

    dialog.refresh_balance()
    assert next(iter(dialog._workers)).wait(3000)
    qapp.processEvents()
    # 查到后说明里换成实际服务商名，措辞仍需说明拿不到用量
    assert "DeepSeek 未提供账户用量查询接口" in dialog._usage_note.text()


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
    store.record_usage(_usage(10, 1), value, at=datetime.now().astimezone())

    dialog = UsageDialog(_settings(), store)
    assert dialog._rows["today"][0].text() == "1"


# ---------- 窗口下方的 API Key 填写入口 ----------


def _fill(dialog, llm="", base="", account=""):
    dialog._llm_key_input.setText(llm)
    dialog._base_url_input.setText(base)
    dialog._account_key_input.setText(account)


def test_save_llm_key_writes_env_and_emits_change(tmp_path, qapp, monkeypatch):
    import pet.config as config

    monkeypatch.setattr(config, "BASE_DIR", tmp_path)
    settings = _settings(with_key=False)
    dialog = UsageDialog(settings, UsageStore(tmp_path / "usage.json"))
    changed = []
    dialog.llm_config_changed.connect(lambda: changed.append(True))
    dialog.refresh_balance = lambda: None

    _fill(dialog, llm="sk-user-llm-key-123")
    dialog._save_api_config()

    env = (tmp_path / ".env").read_text(encoding="utf-8")
    assert "LLM_API_KEY=sk-user-llm-key-123" in env
    assert settings.llm_api_key == "sk-user-llm-key-123"  # pragma: allowlist secret -- 测试假值
    assert dialog._llm_key_input.text() == ""  # 保存后清空，不留明文
    assert changed == [True]  # 推理 key 变了要通知窗口重建客户端


def test_account_key_falls_back_to_llm_key_when_blank(tmp_path, qapp, monkeypatch):
    import pet.config as config

    monkeypatch.setattr(config, "BASE_DIR", tmp_path)
    settings = _settings(with_key=False)
    dialog = UsageDialog(settings, UsageStore(tmp_path / "usage.json"))
    dialog.refresh_balance = lambda: None

    _fill(dialog, llm="sk-user-llm-key-123")
    dialog._save_api_config()

    # 账户 key 留空时沿用推理 key，账户余额立刻可用
    assert settings.account_api_key == "sk-user-llm-key-123"  # pragma: allowlist secret -- 测试假值
    assert dialog._refresh_button.isEnabled() is True


def test_account_key_only_does_not_touch_llm_config(tmp_path, qapp, monkeypatch):
    import pet.config as config

    monkeypatch.setattr(config, "BASE_DIR", tmp_path)
    settings = _settings(with_key=True)
    dialog = UsageDialog(settings, UsageStore(tmp_path / "usage.json"))
    changed = []
    dialog.llm_config_changed.connect(lambda: changed.append(True))
    calls = []
    dialog.refresh_balance = lambda: calls.append(True)

    _fill(dialog, account="sk-account-only-999")
    dialog._save_api_config()

    env = (tmp_path / ".env").read_text(encoding="utf-8")
    assert "ACCOUNT_API_KEY=sk-account-only-999" in env  # pragma: allowlist secret -- 测试假值
    assert "LLM_API_KEY" not in env  # 没填的项不写
    assert settings.account_api_key == "sk-account-only-999"  # pragma: allowlist secret -- 测试假值
    assert changed == []  # 推理配置没变，不需要重建客户端
    assert calls == [True]


def test_base_url_is_normalized_and_applied(tmp_path, qapp, monkeypatch):
    import pet.config as config

    monkeypatch.setattr(config, "BASE_DIR", tmp_path)
    settings = _settings(with_key=True)
    dialog = UsageDialog(settings, UsageStore(tmp_path / "usage.json"))
    dialog.refresh_balance = lambda: None

    _fill(dialog, base="api.example.com/v1/")
    dialog._save_api_config()

    env = (tmp_path / ".env").read_text(encoding="utf-8")
    assert "LLM_BASE_URL=https://api.example.com/v1" in env
    assert settings.llm_base_url == "https://api.example.com/v1"
    # 账户地址原本跟随推理地址，应一起改
    assert settings.account_base_url == "https://api.example.com/v1"


def test_save_with_all_fields_empty_only_hints(tmp_path, qapp, monkeypatch):
    import pet.config as config

    monkeypatch.setattr(config, "BASE_DIR", tmp_path)
    dialog = UsageDialog(_settings(with_key=False), UsageStore(tmp_path / "usage.json"))

    dialog._save_api_config()

    assert "至少填写一项" in dialog._key_hint.text()
    assert not (tmp_path / ".env").exists()


def test_key_hint_masks_keys(tmp_path, qapp):
    settings = _settings(with_key=True)
    settings.llm_api_key = "sk-abcdefghijklmnop"  # pragma: allowlist secret -- 测试假值
    dialog = UsageDialog(settings, UsageStore(tmp_path / "usage.json"))

    assert "已接入" in dialog._key_hint.text()
    assert "sk-abcdefghijklmnop" not in dialog._key_hint.text()


def test_missing_key_hint_points_to_the_entry_below(tmp_path, qapp):
    dialog = UsageDialog(_settings(with_key=False), UsageStore(tmp_path / "usage.json"))

    assert "下方" in dialog._balance_label.text()


# ---------- 跳转至 API 网站 ----------
def test_website_button_opens_configured_site(tmp_path, qapp, monkeypatch):
    opened = []
    monkeypatch.setattr(
        dialog_module,
        "QDesktopServices",
        SimpleNamespace(openUrl=lambda url: opened.append(url.toString())),
    )
    dialog = UsageDialog(_settings(), UsageStore(tmp_path / "usage.json"))

    dialog._website_button.click()
    qapp.processEvents()

    assert opened == ["https://platform.deepseek.com/usage"]  # 控制台用量页，不是接口根


def test_website_override_wins_over_base_url(tmp_path, qapp, monkeypatch):
    opened = []
    monkeypatch.setattr(
        dialog_module,
        "QDesktopServices",
        SimpleNamespace(openUrl=lambda url: opened.append(url.toString())),
    )
    settings = _settings()
    settings.api_website = "platform.deepseek.com"
    dialog = UsageDialog(settings, UsageStore(tmp_path / "usage.json"))

    dialog._website_button.click()

    assert opened == ["https://platform.deepseek.com"]  # 没写协议时补 https


def test_website_button_disabled_without_address(tmp_path, qapp):
    settings = _settings()
    settings.account_base_url = ""
    dialog = UsageDialog(settings, UsageStore(tmp_path / "usage.json"))

    assert dialog._website_button.isEnabled() is False
    assert "未配置" in dialog._website_button.toolTip()


def test_website_hint_follows_saved_base_url(tmp_path, qapp, monkeypatch):
    import pet.config as config

    monkeypatch.setattr(config, "BASE_DIR", tmp_path)
    settings = _settings()
    dialog = UsageDialog(settings, UsageStore(tmp_path / "usage.json"))
    dialog.refresh_balance = lambda: None

    _fill(dialog, base="api.example.com/v1")
    dialog._save_api_config()

    # 未收录的服务商退回站点根
    assert "https://api.example.com/" in dialog._website_button.toolTip()
