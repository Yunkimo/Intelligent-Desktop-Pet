"""天气订阅真实 HTTP/SQLite + 注入天气、微信传输与时钟。"""

import asyncio
import json
from datetime import datetime
from unittest.mock import AsyncMock
from uuid import uuid4

import httpx
import pytest
from app import config, db, wechat_store
from app import weather_subscriptions as store
from app.weather_dispatcher import WeatherDispatcher
from app.wechat_client import WeChatClient, WeChatError


def stamp(text):
    return datetime.fromisoformat(text + "+08:00").timestamp()


BEFORE = stamp("2030-01-01T20:59:00")
DUE = stamp("2030-01-01T21:00:00")
MIDNIGHT = stamp("2030-01-02T00:00:00")


@pytest.fixture
def configured(client, monkeypatch):
    for name, value in {
        "WX_ENABLED": True,
        "WX_APPID": "weather-test-app",
        "WX_SECRET": "mock-only",  # pragma: allowlist secret -- isolated mock
        "WEATHER_WX_TEMPLATE_ID": "weather-template",
        "WEATHER_WX_TEMPLATE_FIELDS": {
            "thing2": "title",
            "date4": "target_date",
            "thing10": "city",
        },
    }.items():
        monkeypatch.setattr(config, name, value)
    session = wechat_store.new_session("weather-owner")
    return session, {"Authorization": "Bearer " + session["session_token"]}


def event(session, *, choice="accept", now=BEFORE, city="长沙"):
    row = store.prepare(session["user_id"], city, now)
    if choice:
        row = store.register(
            session["user_id"], row["event_id"], str(uuid4()), row["template_id"], choice, now
        )
    return row


def forecast(rain=True, status="ok"):
    return {"status": status, "date": "2030-01-02", "rain": rain, "tip": "记得带伞"}


def dispatcher(result, *, now=DUE, send=None):
    api = AsyncMock()
    api.tomorrow.return_value = result
    sender = send if send is not None else AsyncMock()
    return WeatherDispatcher(api, sender, clock=lambda: now), api, sender


def test_http_prepare_register_isolation_and_replay(client, configured):
    session, headers = configured
    url = "/api/weather/subscriptions"
    assert client.post(url, json={"city": "长沙"}).status_code == 401
    assert client.post(url, json={"city": "http://evil"}, headers=headers).status_code == 422
    first = client.post(url, json={"city": "长沙"}, headers=headers)
    assert first.status_code == 201
    row = first.json()
    assert row["status"] == "prepared" and row["template_id"] == "weather-template"
    assert client.post(url, json={"city": "长沙"}, headers=headers).json() == row
    other = wechat_store.new_session("weather-other")
    foreign = {"Authorization": "Bearer " + other["session_token"]}
    one = url + "/" + row["event_id"]
    assert client.get(one, headers=foreign).status_code == 404
    assert client.delete(one, headers=foreign).status_code == 404
    body = {"request_id": str(uuid4()), "template_id": row["template_id"], "result": "accept"}
    assert client.post(one + "/authorization", json=body, headers=foreign).status_code == 404
    accepted = client.post(one + "/authorization", json=body, headers=headers)
    assert accepted.status_code == 200 and accepted.json()["status"] == "pending"
    assert client.post(one + "/authorization", json=body, headers=headers).json() == accepted.json()
    assert len(client.get(url, headers=headers).json()) == 1
    body["result"] = "reject"
    assert client.post(one + "/authorization", json=body, headers=headers).status_code == 409
    assert client.delete(one, headers=headers).json()["status"] == "cancelled"
    assert "openid" not in accepted.json() and "user_id" not in accepted.json()


@pytest.mark.parametrize(
    "rain,status,expected",
    [(True, "ok", "sent"), (False, "ok", "no_rain"), (None, "unknown", "retry_weather")],
)
def test_due_rain_no_rain_unknown(configured, rain, status, expected):
    session, _ = configured
    row = event(session)
    worker, weather, send = dispatcher(forecast(rain, status))
    assert asyncio.run(worker.run_once()) == 1
    result = store.detail(session["user_id"], row["event_id"])
    assert result["status"] == expected
    assert send.await_count == int(expected == "sent")
    assert asyncio.run(worker.run_once()) == 0
    assert weather.tomorrow.await_count == 1
    assert send.await_count == int(expected == "sent")


@pytest.mark.parametrize("choice", [None, "reject", "ban", "filter"])
def test_no_authorization_never_sends(configured, choice):
    session, _ = configured
    event(session, choice=choice)
    worker, weather, send = dispatcher(forecast())
    assert asyncio.run(worker.run_once()) == 0
    weather.tomorrow.assert_not_awaited()
    send.assert_not_awaited()


def test_boundaries_restart_and_next_day(configured):
    session, _ = configured
    row = event(session)
    worker, _, send = dispatcher(forecast(), now=BEFORE)
    assert asyncio.run(worker.run_once()) == 0
    db.init_db()
    worker.clock = lambda: DUE
    assert asyncio.run(worker.run_once()) == 1
    db.init_db()
    assert asyncio.run(worker.run_once()) == 0
    assert store.detail(session["user_id"], row["event_id"])["status"] == "sent"
    send.assert_awaited_once()
    tomorrow = store.prepare(session["user_id"], "长沙", MIDNIGHT)
    assert tomorrow["event_id"] != row["event_id"] and tomorrow["status"] == "prepared"
    assert tomorrow["target_date"] == "2030-01-03"


def test_expired_and_forecast_crossing_midnight(configured):
    session, _ = configured
    row = event(session)
    claim = store.claim_due(DUE)
    assert store.weather_result(claim, forecast(), MIDNIGHT) is None
    assert store.detail(session["user_id"], row["event_id"])["status"] == "expired"
    with pytest.raises(store.WeatherSubscriptionError):
        store.register(
            session["user_id"],
            row["event_id"],
            str(uuid4()),
            row["template_id"],
            "accept",
            MIDNIGHT,
        )


def test_cancel_during_fetch_and_stale_claim(configured):
    session, _ = configured
    row = event(session)
    claim = store.claim_due(DUE)
    assert store.claim_due(DUE) is None
    store.cancel(session["user_id"], row["event_id"])
    assert store.weather_result(claim, forecast(), DUE) is None
    assert store.claim_due(DUE + 120) is None


def test_interrupted_fetch_recovers_send_does_not(configured):
    session, _ = configured
    row = event(session)
    first = store.claim_due(DUE)
    second = store.claim_due(DUE + 120)
    assert second and second["weather_attempts"] > first["weather_attempts"]
    assert store.weather_result(first, forecast(), DUE + 120) is None
    assert store.weather_result(second, forecast(), DUE + 120)
    assert store.claim_due(DUE + 240) is None
    assert store.detail(session["user_id"], row["event_id"])["status"] == "uncertain"


@pytest.mark.parametrize(
    "error,outcome",
    [
        (WeChatError("wechat_no_subscription"), "failed"),
        (WeChatError("network", uncertain=True, retryable=True), "uncertain"),
        (WeChatError("token_busy", retryable=True), "retry"),
        (RuntimeError("transport"), "uncertain"),
    ],
)
def test_delivery_failures(configured, error, outcome):
    session, _ = configured
    row = event(session)
    worker, _, send = dispatcher(forecast(), send=AsyncMock(side_effect=error))
    asyncio.run(worker.run_once())
    assert store.detail(session["user_id"], row["event_id"])["status"] == outcome
    if outcome == "retry":
        worker.clock = lambda: DUE + 301
        send.side_effect = None
        asyncio.run(worker.run_once())
        assert store.detail(session["user_id"], row["event_id"])["status"] == "sent"
    else:
        worker.clock = lambda: DUE + 301
        assert asyncio.run(worker.run_once()) == 0
        send.assert_awaited_once()


def test_unknown_retries_and_template_changes(configured, monkeypatch):
    session, _ = configured
    row = event(session)
    worker, weather, send = dispatcher(forecast(None, "unknown"))
    asyncio.run(worker.run_once())
    weather.tomorrow.return_value = forecast()
    worker.clock = lambda: DUE + 301
    asyncio.run(worker.run_once())
    assert store.detail(session["user_id"], row["event_id"])["status"] == "sent"
    row2 = event(session, city="武汉")
    monkeypatch.setattr(config, "WEATHER_WX_TEMPLATE_ID", "changed")
    asyncio.run(worker.run_once())
    assert (
        store.detail(session["user_id"], row2["event_id"])["last_error"]
        == "weather_template_changed"
    )
    send.assert_awaited_once()


def test_wrong_date_never_sends(configured):
    session, _ = configured
    row = event(session)
    result = {**forecast(), "date": "1999-01-01"}
    worker, _, send = dispatcher(result)
    asyncio.run(worker.run_once())
    send.assert_not_awaited()
    assert store.detail(session["user_id"], row["event_id"])["status"] == "retry_weather"


def test_weather_payload_keeps_ordinary_template(configured, monkeypatch):
    calls = []
    monkeypatch.setattr(config, "WX_TEMPLATE_ID", "ordinary-template")

    def transport(request):
        if request.url.path == "/cgi-bin/token":
            return httpx.Response(200, json={"access_token": "mock-token", "expires_in": 7200})
        calls.append(json.loads(request.content))
        return httpx.Response(200, json={"errcode": 0})

    async def run():
        api = WeChatClient(httpx.MockTransport(transport))
        try:
            await api.send_weather(
                "mock-openid",
                {"event_id": "mock-event", "city": "长沙", "target_date": "2030-01-02"},
            )
        finally:
            await api.close()

    asyncio.run(run())
    assert calls[0]["template_id"] == "weather-template"
    assert calls[0]["data"] == {
        "thing2": {"value": "明日带伞提醒"},
        "date4": {"value": "2030-01-02"},
        "thing10": {"value": "长沙"},
    }
    assert calls[0]["page"] == "pages/index/index?weather_event_id=mock-event"
    assert config.WX_TEMPLATE_ID == "ordinary-template"


def test_migration_backup_and_idempotence(configured):
    before = set(config.DB_PATH.parent.glob("*.pre-weather-subscriptions-*.db"))
    with db._conn() as conn:
        assert (
            conn.execute("SELECT COUNT(*) FROM schema_migrations WHERE version=5").fetchone()[0]
            == 1
        )
        conn.execute("DROP TABLE weather_subscription_requests")
        conn.execute("DROP TABLE weather_subscriptions")
        conn.execute("DELETE FROM schema_migrations WHERE version=5")
    db.init_db()
    snapshots = set(config.DB_PATH.parent.glob("*.pre-weather-subscriptions-*.db")) - before
    assert len(snapshots) == 1
    db.init_db()
    assert set(config.DB_PATH.parent.glob("*.pre-weather-subscriptions-*.db")) - before == snapshots


def test_safe_retries_stop_at_limit(configured):
    session, _ = configured
    row = event(session)
    worker, _, send = dispatcher(
        forecast(), send=AsyncMock(side_effect=WeChatError("token_busy", retryable=True))
    )
    for i in range(config.SCHEDULER_MAX_ATTEMPTS + 1):
        worker.clock = lambda i=i: DUE + i * 301
        asyncio.run(worker.run_once())
    assert send.await_count == config.SCHEDULER_MAX_ATTEMPTS
    assert store.detail(session["user_id"], row["event_id"])["status"] == "failed"


def test_cancel_cannot_claim_recall_after_send_begins(configured):
    session, _ = configured
    row = event(session)
    claim = store.claim_due(DUE)
    sending = store.weather_result(claim, forecast(), DUE)
    assert sending
    with pytest.raises(store.WeatherSubscriptionError, match="weather_send_already_started"):
        store.cancel(session["user_id"], row["event_id"])


def test_disabled_config_and_new_accept_after_reject(client, configured, monkeypatch):
    session, headers = configured
    row = event(session, choice="reject")
    changed = store.register(
        session["user_id"], row["event_id"], str(uuid4()), row["template_id"], "accept", BEFORE
    )
    assert changed["status"] == "pending"
    monkeypatch.setattr(config, "WX_ENABLED", False)
    worker, weather, send = dispatcher(forecast())
    assert asyncio.run(worker.run_once()) == 0
    send.assert_not_awaited()
    weather.tomorrow.assert_not_awaited()
    assert (
        client.post(
            "/api/weather/subscriptions", json={"city": "长沙"}, headers=headers
        ).status_code
        == 503
    )
