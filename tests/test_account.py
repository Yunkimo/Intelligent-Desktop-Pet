"""A19：凭据边界、会话优先级、401 及账号配置窗口。"""

import json

import httpx
import pytest

from pet.account import AccountStore
from pet.account_dialog import AccountDialog
from pet.backend_client import BackendClient, BackendError, SessionExpired, WsListener, build_ws_url


def test_store_scoped_atomic_and_logout(tmp_path):
    path = tmp_path / "data/account.json"
    store = AccountStore(path, "http://server/")
    store.save({"device_token": "test-device-session", "user_id": 2})
    assert store.load()["user_id"] == 2
    assert AccountStore(path, "http://other").load() is None
    assert list(path.parent.glob(".account-*")) == []
    store.clear()
    assert store.load()["signed_out"] is True
    path.write_text("broken")
    with pytest.raises(ValueError, match="损坏"):
        store.load()


def test_headers_bearer_and_fail_closed(monkeypatch):
    client = BackendClient("http://server", "legacy")
    client.session_token = "session-a"
    assert client._headers() == {"Authorization": "Bearer session-a"}
    assert "session-a" in build_ws_url(client.base_url, client.session_token)
    client.session_token = ""
    client.session_required = True
    with pytest.raises(SessionExpired):
        client.list_tasks()


def test_401_does_not_fallback_or_expose_secret(monkeypatch):
    calls = []
    client = BackendClient("http://server", "legacy")
    client.session_token = "session-a"
    client.on_auth_error = lambda: calls.append("expired")

    def request(*args, **kwargs):
        calls.append(kwargs["headers"])
        return httpx.Response(401, text="private-session-a")

    monkeypatch.setattr(httpx, "request", request)
    with pytest.raises(SessionExpired, match="重新绑定") as error:
        client.list_tasks()
    assert calls == [{"Authorization": "Bearer session-a"}, "expired"]
    assert "private-session-a" not in str(error.value)
    assert client.session_token == "session-a"


def test_pairing_payload_not_old_bearer(monkeypatch):
    client = BackendClient("http://server", "legacy")
    client.session_token = "old"
    seen = []

    def request(*args, **kwargs):
        seen.append(kwargs)
        return httpx.Response(200, json={"device_token": "new", "user_id": 2})

    monkeypatch.setattr(httpx, "request", request)
    client.device_login("one-time-code")
    assert seen[0]["headers"] == {}
    assert seen[0]["json"] == {"pairing_code": "one-time-code"}
    with pytest.raises(BackendError, match="配对码"):
        client.device_login("")
    assert len(seen) == 1


def test_dialog_saves_only_to_account_file(qapp, tmp_path):
    store = AccountStore(tmp_path / "data/account.json", "http://server")
    dialog = AccountDialog(BackendClient("http://server", "legacy"), store)
    changed = []
    dialog.changed.connect(changed.append)
    dialog.complete({"device_token": "new-session", "user_id": 3}, "pair")
    assert changed[0]["user_id"] == 3
    assert json.loads(store.path.read_text())["device_token"] == "new-session"
    assert "用户 3" in dialog.status.text()
    dialog.close()


def test_dialog_shows_current_logged_in_account(qapp, tmp_path):
    store = AccountStore(tmp_path / "data/account.json", "http://server")
    store.save({"device_token": "session", "user_id": 7})

    dialog = AccountDialog(BackendClient("http://server", "legacy"), store)

    assert "已登录用户 7" in dialog.status.text()
    assert "http://server" in dialog.status.text()
    assert dialog.buttons[-1].isEnabled()
    dialog.close()


def test_dialog_shows_signed_out_state(qapp, tmp_path):
    store = AccountStore(tmp_path / "data/account.json", "http://server")
    store.clear()

    dialog = AccountDialog(BackendClient("http://server", "legacy"), store)

    assert "未登录" in dialog.status.text()
    assert [button.text() for button in dialog.buttons] == ["配对绑定", "退出并清除本机账号"]
    assert not dialog.buttons[-1].isEnabled()
    dialog.close()


def test_ws_auth_failure_stops_without_leaking(qapp, monkeypatch):
    class AuthError(Exception):
        status_code = 403

    def fail(*args, **kwargs):
        raise AuthError("ws://secret-token")

    monkeypatch.setattr("pet.backend_client.websocket.create_connection", fail)
    listener = WsListener("ws://server/ws?token=private")
    failures = []
    listener.auth_error.connect(lambda: failures.append(True))
    listener.run()
    assert failures == [True]
