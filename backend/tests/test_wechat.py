"""B3 微信 HTTP/身份/授权/调度回归；所有上游调用均由 MockTransport 接管。"""

import asyncio
import hashlib
import json
import logging
import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from unittest.mock import AsyncMock
from uuid import uuid4

import httpx
import pytest
from app import config, db, reminder_store, wechat_store
from app import main as application
from app.reminder_time import utc_text
from app.scheduler import Scheduler
from app.wechat_client import WeChatClient, WeChatError
from app.wechat_dispatcher import WeChatDispatcher
from fastapi.testclient import TestClient

NOW = datetime(2040, 1, 1, tzinfo=timezone.utc).timestamp()
HEADERS = {"X-API-Key": "test-token"}


@pytest.fixture
def wx_config(monkeypatch):
    for name, value in {
        "WX_ENABLED": True,
        "WX_APPID": "test-app",
        "WX_SECRET": "test-secret",  # pragma: allowlist secret -- Mock-only placeholder
        "WX_TEMPLATE_ID": "test-template",
        "WX_TEMPLATE_FIELDS": {"thing1": "title", "time2": "remind_at"},
        "WX_MINIPROGRAM_STATE": "developer",
        "SCHEDULER_ENABLED": False,
        "API_TOKEN": "test-token",
    }.items():
        monkeypatch.setattr(config, name, value)


class FakeWeChat:
    """可定制响应的本地微信替身；不创建任何真实网络连接。"""

    def __init__(self):
        self.calls = []
        self.responses = {}

    def __call__(self, request):
        self.calls.append(request)
        path = request.url.path
        if path in self.responses:
            response = self.responses[path]
            if isinstance(response, Exception):
                raise response
            if callable(response):
                return response(request)
            return httpx.Response(200, json=response)
        if path == "/sns/jscode2session":
            return httpx.Response(
                200,
                json={
                    "openid": "openid-" + request.url.params["js_code"],
                    "session_key": "do-not-return",
                },
            )
        if path == "/cgi-bin/token":
            return httpx.Response(
                200, json={"access_token": "test-access-token", "expires_in": 7200}
            )
        if path == "/cgi-bin/message/subscribe/send":
            return httpx.Response(200, json={"errcode": 0, "errmsg": "ok"})
        raise AssertionError("Unexpected upstream path")

    def count(self, path):
        return sum(request.url.path == path for request in self.calls)


@pytest.fixture
def wx_app(wx_config, monkeypatch, tmp_path):
    fake = FakeWeChat()
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "wechat.db")
    monkeypatch.setattr(
        application, "WeChatClient", lambda: WeChatClient(httpx.MockTransport(fake))
    )
    with TestClient(application.app) as client:
        yield client, fake


def login(client, code="alice"):
    response = client.post("/api/wechat/login", json={"code": code}, headers=HEADERS)
    assert response.status_code == 200, response.text
    identity = response.json()
    return identity, {**HEADERS, "Authorization": "Bearer " + identity["session_token"]}


def register(client, *, channel="phone", result="accept", code="alice", due=NOW):
    identity, headers = login(client, code)
    response = client.post(
        "/api/reminders",
        headers=HEADERS,
        json={
            "title": "复习数学",
            "remind_at": utc_text(due),
            "channel": channel,
            "wechat_user_id": identity["user_id"],
        },
    )
    assert response.status_code == 201, response.text
    reminder = response.json()
    payload = {
        "reminder_id": reminder["id"],
        "template_id": config.WX_TEMPLATE_ID,
        "request_id": str(uuid4()),
        "result": result,
    }
    response = client.post("/api/wechat/subscribe", headers=headers, json=payload)
    assert response.status_code == 200, response.text
    return reminder, identity, headers, payload


def dispatch(client, now=NOW):
    application.app.state.wechat_dispatcher.clock = lambda: now
    return client.portal.call(application.app.state.wechat_dispatcher.run_once)


def test_login_session_rotation_expiry_hash_and_redaction(wx_app, caplog):
    client, fake = wx_app
    caplog.set_level(logging.INFO, logger="httpx")
    identity, headers = login(client)
    assert set(identity) == {"user_id", "openid", "session_token", "expires_in"}
    assert identity["openid"] == "openid-alice"
    assert wechat_store.session_user(identity["session_token"]) == identity["user_id"]
    assert wechat_store.session_user(identity["session_token"], now=NOW) is None
    assert wechat_store.session_user(identity["openid"]) is None
    with db._conn() as conn:
        stored = dict(conn.execute("SELECT * FROM wechat_sessions").fetchone())
    assert stored["token_hash"] == hashlib.sha256(identity["session_token"].encode()).hexdigest()
    assert identity["session_token"] not in str(stored)
    new_identity, _ = login(client)
    assert new_identity["user_id"] == identity["user_id"]
    assert wechat_store.session_user(identity["session_token"]) is None
    assert client.get("/api/wechat/subscriptions/1", headers=headers).status_code == 401
    assert config.WX_SECRET not in caplog.text
    assert "js_code=alice" not in caplog.text
    assert "do-not-return" not in caplog.text
    assert fake.count("/sns/jscode2session") == 2


@pytest.mark.parametrize(
    "payload", [{"code": ""}, {"code": " "}, {"code": "a" * 257}, {"code": "a", "openid": "victim"}]
)
def test_login_validates_input(wx_app, payload):
    client, fake = wx_app
    assert client.post("/api/wechat/login", headers=HEADERS, json=payload).status_code == 422
    assert not fake.calls


@pytest.mark.parametrize(
    "response,status",
    [
        ({"errcode": 40029}, 401),
        ({"errcode": 40163}, 401),
        ({"errcode": 40013, "errmsg": "secret"}, 502),
        ({"openid": ""}, 502),
        ({"openid": None}, 502),
        ({"errcode": {}}, 502),
        ([], 502),
    ],
)
def test_login_upstream_errors_are_sanitized(wx_app, response, status):
    client, fake = wx_app
    fake.responses["/sns/jscode2session"] = response
    result = client.post("/api/wechat/login", headers=HEADERS, json={"code": "alice"})
    assert result.status_code == status
    assert "secret" not in result.text


def test_missing_config_and_api_key_fail_closed(wx_app, monkeypatch):
    client, fake = wx_app
    assert client.post("/api/wechat/login", json={"code": "alice"}).status_code == 401
    monkeypatch.setattr(config, "WX_ENABLED", False)
    assert (
        client.post("/api/wechat/login", headers=HEADERS, json={"code": "alice"}).status_code == 503
    )
    assert not fake.calls


def test_subscribe_is_scoped_and_idempotent(wx_app):
    client, fake = wx_app
    reminder, identity, headers, payload = register(client)
    assert client.post("/api/wechat/subscribe", headers=headers, json=payload).status_code == 200
    _, other = login(client, "bob")
    assert client.post("/api/wechat/subscribe", headers=other, json=payload).status_code == 404
    assert client.get(f"/api/wechat/subscriptions/{reminder['id']}", headers=other).json() == []
    assert client.post("/api/wechat/subscribe", headers=HEADERS, json=payload).status_code == 401
    assert (
        client.post(
            "/api/wechat/subscribe", headers=headers, json={**payload, "openid": "other"}
        ).status_code
        == 422
    )
    assert (
        client.post(
            "/api/wechat/subscribe", headers=headers, json={**payload, "result": "reject"}
        ).status_code
        == 409
    )
    assert (
        client.post(
            "/api/wechat/subscribe", headers=headers, json={**payload, "request_id": str(uuid4())}
        ).status_code
        == 409
    )
    assert (
        client.post(
            "/api/wechat/subscribe", headers=headers, json={**payload, "template_id": "wrong"}
        ).status_code
        == 422
    )
    assert dispatch(client) == 1
    assert dispatch(client) == 0
    assert fake.count("/cgi-bin/message/subscribe/send") == 1
    assert wechat_store.status(reminder["id"])[0]["status"] == "sent"
    assert db.list_reminders()[0]["done"] == 1
    send = fake.calls[-1]
    assert send.url.host == "api.weixin.qq.com"
    assert json.loads(send.content)["touser"] == identity["openid"]
    assert json.loads(send.content)["data"] == {
        "thing1": {"value": "复习数学"},
        "time2": {"value": "2040-01-01 08:00"},
    }


@pytest.mark.parametrize("choice", ["reject", "ban", "filter"])
def test_declined_subscription_does_not_send_and_can_be_accepted_later(wx_app, choice):
    client, fake = wx_app
    reminder, _, headers, payload = register(client, result=choice)
    assert dispatch(client) == 0
    assert fake.count("/cgi-bin/message/subscribe/send") == 0
    response = client.post(
        "/api/wechat/subscribe",
        headers=headers,
        json={**payload, "result": "accept", "request_id": str(uuid4())},
    )
    assert response.status_code == 200
    assert dispatch(client) == 1
    assert wechat_store.status(reminder["id"])[0]["status"] == "sent"


def test_due_time_boundaries_and_both_channels_are_independent(wx_app):
    client, fake = wx_app
    reminder, _, _, _ = register(client, channel="both", due=NOW + 1)
    assert dispatch(client, NOW) == 0
    websocket = AsyncMock(return_value=1)
    application.app.state.wechat_dispatcher.clock = lambda: NOW + 1
    scheduler = Scheduler(
        websocket, lambda: NOW + 1, application.app.state.wechat_dispatcher.run_once
    )
    assert client.portal.call(scheduler.run_once) == 2
    assert reminder_store.delivery_status(reminder["id"])["status"] == "sent"
    assert wechat_store.status(reminder["id"])[0]["status"] == "sent"
    assert fake.count("/cgi-bin/message/subscribe/send") == 1


def test_phone_sends_when_desktop_is_offline_without_preventing_ws_retry(wx_app):
    client, fake = wx_app
    reminder, _, _, _ = register(client, channel="both")
    application.app.state.wechat_dispatcher.clock = lambda: NOW
    scheduler = Scheduler(
        AsyncMock(return_value=0), lambda: NOW, application.app.state.wechat_dispatcher.run_once
    )
    assert client.portal.call(scheduler.run_once) == 2
    assert reminder_store.delivery_status(reminder["id"])["status"] == "retry"
    assert wechat_store.status(reminder["id"])[0]["status"] == "sent"
    assert db.list_reminders()[0]["done"] == 0
    assert dispatch(client, NOW + 100) == 0


@pytest.mark.parametrize(
    "response,reason",
    [
        ({"errcode": 43101}, "wechat_no_subscription"),
        ({"errcode": 40037}, "wechat_invalid_template"),
        ({"errcode": 47003}, "wechat_invalid_fields"),
        ({"errcode": 40003}, "wechat_invalid_recipient"),
        ({"errcode": 45009}, "wechat_rate_limited"),
        ({"errcode": 41030}, "wechat_invalid_page"),
        ({"errcode": -1}, "wechat_send_rejected"),
    ],
)
def test_platform_rejection_is_terminal_not_false_success(wx_app, response, reason):
    client, fake = wx_app
    reminder, _, _, _ = register(client)
    fake.responses["/cgi-bin/message/subscribe/send"] = {**response, "errmsg": "sensitive body"}
    assert dispatch(client) == 1
    state = wechat_store.status(reminder["id"])[0]
    assert state["status"] == "failed"
    assert state["last_error"] == reason
    assert db.list_reminders()[0]["done"] == 0
    assert dispatch(client, NOW + 1000) == 0
    assert fake.count("/cgi-bin/message/subscribe/send") == 1


@pytest.mark.parametrize(
    "response",
    [
        httpx.ReadTimeout("private-url"),
        {"errmsg": "not enough"},
        lambda request: httpx.Response(500),
        lambda request: httpx.Response(200, text="bad-json"),
    ],
)
def test_unknown_send_outcome_is_never_automatically_retried(wx_app, response):
    client, fake = wx_app
    reminder, _, _, _ = register(client)
    fake.responses["/cgi-bin/message/subscribe/send"] = response
    assert dispatch(client) == 1
    assert wechat_store.status(reminder["id"])[0]["status"] == "uncertain"
    assert dispatch(client, NOW + 1000) == 0
    assert fake.count("/cgi-bin/message/subscribe/send") == 1


def test_token_failure_before_send_retries_with_limit(wx_app):
    client, fake = wx_app
    reminder, _, _, _ = register(client)
    fake.responses["/cgi-bin/token"] = httpx.ConnectError("private-secret")
    for offset in (0, 30, 90):
        assert dispatch(client, NOW + offset) == 1
    assert wechat_store.status(reminder["id"])[0]["status"] == "failed"
    assert fake.count("/cgi-bin/message/subscribe/send") == 0
    assert dispatch(client, NOW + 1000) == 0


def test_restart_after_send_claim_marks_uncertain(wx_app):
    client, fake = wx_app
    reminder, _, _, _ = register(client)
    claim = wechat_store.claim_due(NOW)
    assert claim is not None
    assert dispatch(client, NOW) == 0
    assert dispatch(client, NOW + config.WX_DELIVERY_LEASE_SECONDS) == 0
    assert wechat_store.status(reminder["id"])[0]["status"] == "uncertain"
    assert fake.count("/cgi-bin/message/subscribe/send") == 0


@pytest.mark.parametrize(
    "change",
    [
        {"done": True},
        {"title": "修改"},
        {"remind_at": "2041-01-01T00:00:00Z"},
        {"wechat_user_id": None},
    ],
)
def test_edits_invalidate_pending_authorization(wx_app, change):
    client, fake = wx_app
    reminder, _, _, _ = register(client)
    db.update_reminder(reminder["id"], change)
    assert dispatch(client) == 0
    assert wechat_store.status(reminder["id"])[0]["status"] == "cancelled"


def test_delete_and_unknown_recipient_are_safe(wx_app):
    client, fake = wx_app
    reminder, _, _, _ = register(client)
    db.delete_reminder(reminder["id"])
    assert dispatch(client) == 0
    assert wechat_store.status(reminder["id"]) == []
    response = client.post(
        "/api/reminders",
        headers=HEADERS,
        json={"title": "x", "remind_at": utc_text(NOW), "wechat_user_id": 999},
    )
    assert response.status_code == 422


def test_upgrade_is_idempotent_and_keeps_b2_event_ids(wx_app):
    client, _ = wx_app
    reminder, _, _, _ = register(client)
    event = reminder_store.delivery_status(reminder["id"])["event_id"]
    db.init_db()
    db.init_db()
    assert reminder_store.delivery_status(reminder["id"])["event_id"] == event
    assert len(wechat_store.status(reminder["id"])) == 1
    with closing(sqlite3.connect(config.DB_PATH)) as conn:
        assert (
            conn.execute("SELECT COUNT(*) FROM schema_migrations WHERE version=2").fetchone()[0]
            == 1
        )


def test_access_token_single_flight_expiry_and_refresh(wx_config):
    async def scenario():
        clock = [0]
        fake = FakeWeChat()
        fake.responses["/cgi-bin/token"] = lambda request: httpx.Response(
            200, json={"access_token": f"test-{fake.count('/cgi-bin/token')}", "expires_in": 100}
        )
        api = WeChatClient(httpx.MockTransport(fake), lambda: clock[0])
        try:
            assert await asyncio.gather(*(api.access_token() for _ in range(10))) == ["test-1"] * 10
            assert fake.count("/cgi-bin/token") == 1
            clock[0] = 91
            assert await api.access_token() == "test-2"
            assert (
                await asyncio.gather(
                    *(api.access_token(rejected_token="test-2") for _ in range(10))
                )
                == ["test-3"] * 10
            )
            assert fake.count("/cgi-bin/token") == 3
        finally:
            await api.close()

    asyncio.run(scenario())


@pytest.mark.parametrize("code", [40001, 40014, 42001])
def test_rejected_token_refreshes_once_then_succeeds(wx_app, code):
    client, fake = wx_app
    reminder, _, _, _ = register(client)

    def send(request):
        return httpx.Response(
            200, json={"errcode": code if fake.count(request.url.path) == 1 else 0}
        )

    fake.responses["/cgi-bin/message/subscribe/send"] = send
    assert dispatch(client) == 1
    assert wechat_store.status(reminder["id"])[0]["status"] == "sent"
    assert fake.count("/cgi-bin/token") == 2
    assert fake.count("/cgi-bin/message/subscribe/send") == 2


def test_repeated_token_rejection_is_bounded(wx_app):
    client, fake = wx_app
    reminder, _, _, _ = register(client)
    fake.responses["/cgi-bin/message/subscribe/send"] = {"errcode": 42001}
    assert dispatch(client) == 1
    assert wechat_store.status(reminder["id"])[0]["status"] == "failed"
    assert fake.count("/cgi-bin/token") == 2
    assert fake.count("/cgi-bin/message/subscribe/send") == 2


@pytest.mark.parametrize(
    "reply",
    [
        {"access_token": "x", "expires_in": 0},
        {"access_token": "x", "expires_in": True},
        {"access_token": "x", "expires_in": float("inf")},
        {"access_token": None, "expires_in": 100},
        {"errcode": {}},
        {"errcode": 40013},
    ],
)
def test_invalid_token_response_does_not_send(wx_config, reply):
    async def scenario():
        fake = FakeWeChat()
        # json.dumps 允许 Infinity，模拟不规范上游，httpx 的 json= 序列化则会先拒绝它。
        fake.responses["/cgi-bin/token"] = lambda request: httpx.Response(
            200, text=json.dumps(reply)
        )
        api = WeChatClient(httpx.MockTransport(fake))
        try:
            with pytest.raises(WeChatError):
                await api.access_token()
        finally:
            await api.close()

    asyncio.run(scenario())


def test_concurrent_dispatch_consumes_once(wx_app):
    client, fake = wx_app
    reminder, _, _, _ = register(client)

    async def scenario():
        send = application.app.state.push_service.send_wechat_msg
        workers = [WeChatDispatcher(send, lambda: NOW) for _ in range(4)]
        return await asyncio.gather(*(worker.run_once() for worker in workers))

    assert sum(client.portal.call(scenario)) == 1
    assert fake.count("/cgi-bin/message/subscribe/send") == 1


def test_cancel_during_send_persists_uncertain(wx_app):
    client, _ = wx_app
    reminder, _, _, _ = register(client)

    async def scenario():
        entered = asyncio.Event()

        async def send(*args):
            entered.set()
            await asyncio.Event().wait()

        task = asyncio.create_task(WeChatDispatcher(send, lambda: NOW).run_once())
        await asyncio.wait_for(entered.wait(), 2)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    client.portal.call(scenario)
    assert wechat_store.status(reminder["id"])[0]["status"] == "uncertain"


def test_disabled_channel_and_missing_template_do_not_send(wx_app, monkeypatch):
    client, fake = wx_app
    _, _, headers, payload = register(client)
    monkeypatch.setattr(config, "WX_ENABLED", False)
    assert dispatch(client) == 0
    monkeypatch.setattr(config, "WX_ENABLED", True)
    monkeypatch.setattr(config, "WX_TEMPLATE_FIELDS", {})
    assert client.post("/api/wechat/subscribe", headers=headers, json=payload).status_code == 503
    assert dispatch(client) == 1
    assert fake.count("/cgi-bin/message/subscribe/send") == 0


def test_non_phone_completed_and_long_session_inputs_are_rejected(wx_app):
    client, _ = wx_app
    identity, headers = login(client)
    item = db.create_reminder(
        "测试", utc_text(NOW), channel="pc", wechat_user_id=identity["user_id"]
    )
    payload = {
        "reminder_id": item["id"],
        "request_id": str(uuid4()),
        "template_id": config.WX_TEMPLATE_ID,
        "result": "accept",
    }
    assert client.post("/api/wechat/subscribe", headers=headers, json=payload).status_code == 409
    db.update_reminder(item["id"], {"channel": "phone", "done": True})
    assert client.post("/api/wechat/subscribe", headers=headers, json=payload).status_code == 409
    assert wechat_store.session_user("a" * 257) is None
    assert wechat_store.session_user("") is None
    assert (
        client.put(
            f"/api/reminders/{item['id']}", headers=HEADERS, json={"wechat_user_id": 9999}
        ).status_code
        == 422
    )


def test_template_change_fails_existing_grant(wx_app, monkeypatch):
    client, fake = wx_app
    reminder, _, _, _ = register(client)
    monkeypatch.setattr(config, "WX_TEMPLATE_ID", "changed-template")
    assert dispatch(client) == 1
    assert wechat_store.status(reminder["id"])[0]["last_error"] == "wechat_template_changed"
    assert fake.count("/cgi-bin/message/subscribe/send") == 0


def test_edit_between_claim_and_send_skips_notification(wx_app, monkeypatch):
    client, fake = wx_app
    reminder, _, _, _ = register(client)
    original = wechat_store.is_current

    def edit(claim):
        db.update_reminder(reminder["id"], {"done": True})
        return original(claim)

    monkeypatch.setattr(wechat_store, "is_current", edit)
    assert dispatch(client) == 0
    assert wechat_store.status(reminder["id"])[0]["status"] == "cancelled"
    assert fake.count("/cgi-bin/message/subscribe/send") == 0


def test_dispatch_deadline_keeps_uncertain_state(wx_app, monkeypatch):
    client, _ = wx_app
    reminder, _, _, _ = register(client)

    async def send(*args):
        await asyncio.Event().wait()

    monkeypatch.setattr(config, "WX_DELIVERY_TIMEOUT_SECONDS", 0.01)
    assert client.portal.call(WeChatDispatcher(send, lambda: NOW).run_once) == 1
    assert wechat_store.status(reminder["id"])[0]["status"] == "uncertain"


def test_b2_database_upgrade_preserves_existing_reminders(wx_config, monkeypatch, tmp_path):
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "b2.db")
    with db._conn() as conn:
        conn.executescript(db._SCHEMA)
        conn.execute(
            "INSERT INTO reminders(title,remind_at) VALUES (?,?)", ("升级前", utc_text(NOW))
        )
        conn.commit()
        reminder_store.migrate(conn)
    event = reminder_store.delivery_status(1)["event_id"]
    db.init_db()
    db.init_db()
    assert reminder_store.delivery_status(1)["event_id"] == event
    assert db.list_reminders()[0]["title"] == "升级前"
    assert db.list_reminders()[0]["wechat_user_id"] is None
    identity = wechat_store.new_session("openid-alice")
    db.update_reminder(1, {"wechat_user_id": identity["user_id"]})
    assert db.list_reminders()[0]["wechat_user_id"] == identity["user_id"]


def test_slow_phone_channel_does_not_delay_desktop_scans(wx_app, monkeypatch):
    client, _ = wx_app
    monkeypatch.setattr(config, "SCHEDULER_INTERVAL_SECONDS", 0.01)

    async def scenario():
        entered = asyncio.Event()
        delivered = asyncio.Event()

        async def slow_phone():
            entered.set()
            await asyncio.Event().wait()

        async def broadcast(event):
            delivered.set()
            return 1

        scheduler = Scheduler(broadcast, lambda: NOW, slow_phone)
        scheduler.start()
        phone_task = scheduler._phone_task
        scheduler.start()
        assert scheduler._phone_task is phone_task
        try:
            await asyncio.wait_for(entered.wait(), 2)
            db.create_reminder("桌面仍可提醒", utc_text(NOW), channel="pc")
            await asyncio.wait_for(delivered.wait(), 2)
        finally:
            await scheduler.stop()
        assert phone_task.done()
        assert scheduler._phone_task is None

    client.portal.call(scenario)


def test_send_success_before_database_failure_does_not_repeat(wx_app, monkeypatch):
    client, fake = wx_app
    reminder, _, _, _ = register(client)
    original = wechat_store.finish

    def fail(*args):
        raise sqlite3.OperationalError("simulated write failure")

    monkeypatch.setattr(wechat_store, "finish", fail)
    with pytest.raises(sqlite3.OperationalError):
        dispatch(client)
    monkeypatch.setattr(wechat_store, "finish", original)
    assert dispatch(client, NOW + config.WX_DELIVERY_LEASE_SECONDS) == 0
    assert wechat_store.status(reminder["id"])[0]["status"] == "uncertain"
    assert fake.count("/cgi-bin/message/subscribe/send") == 1
