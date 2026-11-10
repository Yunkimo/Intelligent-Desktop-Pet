"""B5 扩展：跨周期与事务边界，天气降水、缓存和故障降级。"""

import asyncio
import json
from datetime import datetime, timezone
from unittest.mock import AsyncMock
from uuid import uuid4

import httpx
import pytest
from app import config, db, recurrence, reminder_store, wechat_store
from app.main import app
from app.reminder_time import utc_text
from app.scheduler import Scheduler
from app.weather_tips import WeatherTips
from app.web_query import WebQueryClient, WebQueryError

NOW = 1900000000.0
KEY = {"X-API-Key": "test-token"}


def weekly(**kwargs):
    return db.create_reminder("weekly", utc_text(NOW), repeat_rule="weekly", channel="pc", **kwargs)


def test_two_cycles_stable_ids_and_stop(client):
    row = weekly()
    sent = []

    async def broadcast(event):
        sent.append(event)
        return 1

    scheduler = Scheduler(broadcast, clock=lambda: NOW)
    assert asyncio.run(scheduler.run_once()) == 1
    first = db.list_reminders()[0]
    assert (
        first["done"] == 0
        and datetime.fromisoformat(first["remind_at"]).timestamp() == NOW + recurrence.WEEK
    )
    assert asyncio.run(scheduler.run_once()) == 0
    scheduler.clock = lambda: NOW + recurrence.WEEK
    assert asyncio.run(scheduler.run_once()) == 1
    assert len({e["event_id"] for e in sent}) == 2
    assert db.list_reminders()[0]["id"] == row["id"]
    db.update_reminder(row["id"], {"repeat_rule": None})
    scheduler.clock = lambda: NOW + 3 * recurrence.WEEK
    assert asyncio.run(scheduler.run_once()) == 0
    assert db.list_reminders()[0]["done"] == 1
    with db._conn() as conn:
        assert conn.execute("SELECT COUNT(*) FROM reminder_occurrences").fetchone()[0] == 2


def test_missed_weeks_skip_and_restart_preserves(client):
    row = weekly()
    recurrence.maintain(NOW + 4 * recurrence.WEEK + 2)
    assert reminder_store.claim_due(NOW + 4 * recurrence.WEEK + 2) is None
    assert (
        datetime.fromisoformat(db.list_reminders()[0]["remind_at"]).timestamp()
        == NOW + 5 * recurrence.WEEK
    )
    event = reminder_store.delivery_status(row["id"])["event_id"]
    db.init_db()
    assert reminder_store.delivery_status(row["id"])["event_id"] == event
    with db._conn() as conn:
        assert conn.execute("SELECT status FROM reminder_occurrences").fetchone()[0] == "skipped"


def test_failed_send_retry_then_next_cycle(client):
    row = weekly()
    claim = reminder_store.claim_due(NOW)
    reminder_store.finish(claim, NOW, "no_clients")
    assert db.list_reminders()[0]["remind_at"] == row["remind_at"]
    due = NOW + config.SCHEDULER_RETRY_SECONDS
    claim2 = reminder_store.claim_due(due)
    assert claim2["event_id"] == claim["event_id"]
    reminder_store.finish(claim2, due, None)
    assert reminder_store.delivery_status(row["id"])["event_id"] != claim["event_id"]
    assert reminder_store.finish(claim, NOW, None) is False


def test_repeat_advance_rolls_back_on_seed_error(client, monkeypatch):
    row = weekly()
    claim = reminder_store.claim_due(NOW)
    monkeypatch.setattr(
        reminder_store, "seed_delivery", lambda *_: (_ for _ in ()).throw(RuntimeError("injected"))
    )
    with pytest.raises(RuntimeError):
        reminder_store.finish(claim, NOW, None)
    assert db.list_reminders()[0]["remind_at"] == row["remind_at"]
    assert reminder_store.is_current(claim)


@pytest.mark.parametrize("change", [{"done": True}, {"repeat_rule": None}])
def test_explicit_stop_invalidates_old_claim(client, change):
    row = weekly()
    claim = reminder_store.claim_due(NOW)
    db.update_reminder(row["id"], change)
    assert reminder_store.finish(claim, NOW, None) is False
    recurrence.maintain(NOW + 10 * recurrence.WEEK)
    assert reminder_store.claim_due(NOW + 10 * recurrence.WEEK) is None


def test_phone_weekly_requires_new_authorization(client):
    identity = wechat_store.new_session("a")
    row = db.create_reminder(
        "weekly-phone",
        utc_text(NOW),
        channel="phone",
        repeat_rule="weekly",
        wechat_user_id=identity["user_id"],
        user_id=identity["account_id"],
    )

    def subscribe():
        return wechat_store.subscribe(
            identity["user_id"], row["id"], str(uuid4()), "template", "accept"
        )

    subscribe()
    first = wechat_store.claim_due(NOW)
    wechat_store.finish(first, NOW, "sent", None)
    assert wechat_store.claim_due(NOW + recurrence.WEEK) is None
    assert db.list_reminders(identity["account_id"])[0]["done"] == 0
    subscribe()
    second = wechat_store.claim_due(NOW + recurrence.WEEK)
    assert second["event_id"] != first["event_id"]
    wechat_store.finish(second, NOW + recurrence.WEEK, "sent", None)


def test_repeat_api_validation_and_user_isolation(client):
    payload = {"title": "weekly", "remind_at": utc_text(NOW), "repeat_rule": "monthly"}
    assert client.post("/api/reminders", headers=KEY, json=payload).status_code == 422
    task = db.create_task("linked", remind_at=utc_text(NOW))
    assert (
        client.post(
            "/api/reminders",
            headers=KEY,
            json={**payload, "repeat_rule": "weekly", "task_id": task["id"]},
        ).status_code
        == 422
    )
    identity = wechat_store.new_session("other")
    other = {"Authorization": "Bearer " + identity["session_token"]}
    created = client.post(
        "/api/reminders", headers=KEY, json={**payload, "repeat_rule": "weekly", "channel": "pc"}
    )
    assert created.status_code == 201 and created.json()["repeat_rule"] == "weekly"
    rid = created.json()["id"]
    assert (
        client.put(f"/api/reminders/{rid}", headers=other, json={"repeat_rule": None}).status_code
        == 404
    )
    assert client.get(f"/api/reminders/{rid}", headers=KEY).json()["repeat_rule"] == "weekly"


def test_one_shot_unchanged(client):
    r = db.create_reminder("one", utc_text(NOW), channel="pc")
    claim = reminder_store.claim_due(NOW)
    reminder_store.finish(claim, NOW, None)
    assert db._get_by_id("reminders", r["id"])["done"] == 1
    assert reminder_store.claim_due(NOW + recurrence.WEEK) is None


@pytest.mark.parametrize(
    "code,rain,desc",
    [
        (113, False, "晴"),
        (125, False, "Haze"),
        (146, False, "Smoke"),
        (149, False, "Smoky haze"),
        (152, False, "Smog"),
        (296, True, "小雨"),
        (389, True, "雷阵雨"),
        (338, True, "大雪"),
    ],
)
def test_structured_forecast_cache_idempotent(client, code, rain, desc):
    calls = []
    now = datetime(2030, 1, 1, 21, tzinfo=timezone.utc)
    target = "2030-01-03"  # 上海已是 1 月 2 日

    def upstream(request):
        calls.append(request)
        payload = {
            "weather": [
                {
                    "date": target,
                    "hourly": [{"weatherCode": str(code), "lang_zh": [{"value": desc}]}],
                }
            ]
        }
        return httpx.Response(200, stream=httpx.ByteStream(json.dumps(payload).encode()))

    async def run():
        api = WebQueryClient(httpx.MockTransport(upstream))
        service = WeatherTips(api)
        try:
            results = await asyncio.gather(*(service.tomorrow("北京", now) for _ in range(5)))
            assert all(r["rain"] is rain and r["date"] == target for r in results)
            assert bool(results[0]["tip"]) is rain
            assert len(calls) == 1
        finally:
            await api.close()

    asyncio.run(run())
    with db._conn() as conn:
        assert conn.execute("SELECT COUNT(*) FROM weather_tip_cache").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM weather_tips").fetchone()[0] == int(rain)


def test_weather_unknown_not_sunny_and_no_tip(client):
    api = AsyncMock()
    api.forecast.side_effect = WebQueryError("upstream_timeout", 504)
    app.state.weather_tips = WeatherTips(api)
    for _ in range(2):
        r = client.get("/api/weather/tomorrow?city=Beijing", headers=KEY)
        assert r.status_code == 200 and r.json()["status"] == "unknown" and r.json()["rain"] is None
    assert api.forecast.await_count == 1
    assert client.get("/api/weather/tomorrow?city=Beijing").status_code == 401
    assert client.get("/api/weather/tomorrow?city=http://evil", headers=KEY).status_code == 422
    with db._conn() as conn:
        assert conn.execute("SELECT COUNT(*) FROM weather_tips").fetchone()[0] == 0


def test_daily_tick_before_after_21_and_no_desktop(client, monkeypatch):
    from zoneinfo import ZoneInfo

    api = AsyncMock()
    api.forecast.return_value = {"rain": True, "desc": "小雨", "tip": "明天有小雨，记得带伞"}
    service = WeatherTips(api)
    monkeypatch.setattr(config, "WEATHER_TIP_CITY", "北京")

    async def run():
        assert (
            await service.tick(datetime(2030, 1, 1, 20, 59, tzinfo=ZoneInfo("Asia/Shanghai")))
            is None
        )
        await service.tick(datetime(2030, 1, 1, 21, tzinfo=ZoneInfo("Asia/Shanghai")))
        await service.tick(datetime(2030, 1, 1, 22, tzinfo=ZoneInfo("Asia/Shanghai")))
        assert api.forecast.await_count == 1

    asyncio.run(run())


def test_forecast_wrong_date_rejected(client):
    async def run():
        api = WebQueryClient(
            httpx.MockTransport(
                lambda r: httpx.Response(
                    200,
                    stream=httpx.ByteStream(b'{"weather": [{"date":"1999-01-01","hourly":[]}]}'),
                )
            )
        )
        try:
            with pytest.raises(WebQueryError):
                await api.forecast("Beijing", "2030-01-02")
        finally:
            await api.close()

    asyncio.run(run())


def test_both_waits_for_authorized_phone_without_duplicate_pc(client):
    identity = wechat_store.new_session("both-owner")
    row = db.create_reminder(
        "both",
        utc_text(NOW),
        channel="both",
        repeat_rule="weekly",
        wechat_user_id=identity["user_id"],
        user_id=identity["account_id"],
    )
    wechat_store.subscribe(identity["user_id"], row["id"], str(uuid4()), "template", "accept")
    pc = reminder_store.claim_due(NOW)
    reminder_store.finish(pc, NOW, None)
    assert reminder_store.delivery_status(row["id"])["event_id"] == pc["event_id"]
    assert reminder_store.claim_due(NOW) is None
    phone = wechat_store.claim_due(NOW)
    wechat_store.finish(phone, NOW, "sent", None)
    assert reminder_store.delivery_status(row["id"])["event_id"] != pc["event_id"]
    assert db.list_reminders(identity["account_id"])[0]["done"] == 0


def test_clear_repeat_null_validation_and_migration_once(client, tmp_path):
    row = weekly()
    backups = set(config.DB_PATH.parent.glob("*.pre-b5-repeat-*.db"))
    db.init_db()
    assert set(config.DB_PATH.parent.glob("*.pre-b5-repeat-*.db")) == backups
    assert (
        client.put(
            f"/api/reminders/{row['id']}", headers=KEY, json={"repeat_rule": "daily"}
        ).status_code
        == 422
    )
    result = client.put(f"/api/reminders/{row['id']}", headers=KEY, json={"repeat_rule": None})
    assert (
        result.status_code == 200
        and result.json()["done"] == 1
        and result.json()["repeat_rule"] is None
    )


def test_real_http_ws_two_weekly_events_and_weather_route(client):
    """真实 FastAPI/SQLite/WS 信封，只有外部天气服务替换。"""
    due = utc_text(NOW)
    with client.websocket_connect("/ws?token=test-token") as ws:
        response = client.post(
            "/api/reminders",
            headers=KEY,
            json={
                "title": "weekly-http",
                "remind_at": due,
                "channel": "pc",
                "repeat_rule": "weekly",
            },
        )
        assert response.status_code == 201
        rid = response.json()["id"]
        scheduler = Scheduler(app.state.push_service.broadcast, lambda: NOW)
        assert client.portal.call(scheduler.run_once) == 1
        first = ws.receive_json()
        scheduler.clock = lambda: NOW + recurrence.WEEK
        assert client.portal.call(scheduler.run_once) == 1
        second = ws.receive_json()
        assert first["data"]["id"] == second["data"]["id"] == rid
        assert first["event_id"] != second["event_id"]
        assert client.delete(f"/api/reminders/{rid}", headers=KEY).status_code == 204
        assert client.portal.call(scheduler.run_once) == 0
    api = AsyncMock()
    api.forecast.return_value = {"rain": True, "desc": "小雨", "tip": "明天有小雨，记得带伞"}
    app.state.weather_tips = WeatherTips(api)
    result = client.get("/api/weather/tomorrow", params={"city": "北京"}, headers=KEY)
    assert (
        result.status_code == 200
        and result.json()["rain"] is True
        and "带伞" in result.json()["tip"]
    )
    assert (
        client.get("/api/weather/tomorrow", params={"city": "北京"}, headers=KEY).json()
        == result.json()
    )
    assert api.forecast.await_count == 1
