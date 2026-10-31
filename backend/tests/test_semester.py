"""B6 日历边界、持久化和事务后通知回归。"""

from datetime import datetime, timezone
from unittest.mock import AsyncMock

import pytest
from app import db, semester
from app.main import app

HEADERS = {"X-API-Key": "test-token"}
SETTINGS = {"start_date": "2026-09-07", "total_weeks": 18, "timezone": "Asia/Shanghai"}
COURSE = {"name": "数学", "day_of_week": 5, "start_time": "08:00", "end_time": "09:40"}


def setup_term(client, **changes):
    response = client.put("/api/semester", headers=HEADERS, json={**SETTINGS, **changes})
    assert response.status_code == 200
    return response.json()


def test_unconfigured_and_auth(client):
    assert client.get("/api/semester").status_code == 401
    assert client.get("/api/calendar").status_code == 401
    assert client.put("/api/semester", json=SETTINGS).status_code == 401
    assert client.get("/api/semester", headers=HEADERS).json() == {
        "configured": False,
        "settings": None,
    }
    result = client.get("/api/calendar?date=2026-10-30", headers=HEADERS).json()
    assert result["status"] == "unconfigured"
    assert result["week"] is None and result["courses"] == []


@pytest.mark.parametrize(
    ("day", "week", "status"),
    [
        ("2026-09-06", None, "before_term"),
        ("2026-09-07", 1, "in_term"),
        ("2026-10-25", 7, "in_term"),
        ("2026-10-26", 8, "in_term"),
        ("2026-10-30", 8, "in_term"),
        ("2027-01-10", 18, "in_term"),
        ("2027-01-11", None, "after_term"),
    ],
)
def test_calendar_boundaries_and_persistence(client, day, week, status):
    expected = setup_term(client)
    db.init_db()  # 模拟重启初始化，不覆盖已保存设置。
    result = client.get("/api/calendar", params={"date": day}, headers=HEADERS).json()
    assert (result["week"], result["status"]) == (week, status)
    assert client.get("/api/semester", headers=HEADERS).json() == expected
    with db._conn() as conn:
        assert conn.execute("SELECT COUNT(*) FROM semester_settings").fetchone()[0] == 1


@pytest.mark.parametrize(
    "patch",
    [
        {"start_date": "2026-09-08"},
        {"start_date": "2026-02-30"},
        {"start_date": 0},
        {"start_date": "2026-09-07T00:00:00"},
        {"total_weeks": 0},
        {"total_weeks": 54},
        {"total_weeks": True},
        {"total_weeks": "18"},
        {"timezone": "Mars/Test"},
        {"timezone": "../UTC"},
        {"user_id": 2},
        {"scope": "other"},
    ],
)
def test_invalid_settings_no_write_or_notification(client, monkeypatch, patch):
    notify = AsyncMock()
    monkeypatch.setattr(app.state.push_service, "notify", notify)
    assert (
        client.put("/api/semester", headers=HEADERS, json={**SETTINGS, **patch}).status_code == 422
    )
    assert semester.get_settings()["configured"] is False
    notify.assert_not_awaited()


def test_date_validation(client):
    assert client.get("/api/calendar?date=not-date", headers=HEADERS).status_code == 422
    assert client.get("/api/calendar?date=2026-02-30", headers=HEADERS).status_code == 422


def test_week_filter_and_historical_bad_weeks(client):
    setup_term(client)
    for name, weeks in [
        ("every", []),
        ("odd", [1, 3, 5, 7, 9]),
        ("even", [2, 4, 6, 8]),
        ("specific", [7, 11]),
    ]:
        db.create_course(**{**COURSE, "name": name, "weeks": weeks})
    db.create_course(**{**COURSE, "name": "other_day", "day_of_week": 1})
    broken = db.create_course(**{**COURSE, "name": "bad"})
    with db._conn() as conn:
        conn.execute("UPDATE courses SET weeks='bad-json' WHERE id=?", (broken["id"],))
    result = client.get("/api/calendar?date=2026-10-30", headers=HEADERS).json()
    assert result["day_of_week"] == 5
    assert {r["name"] for r in result["courses"]} == {"every", "even"}
    result = client.get("/api/calendar?date=2026-10-23", headers=HEADERS).json()
    assert {r["name"] for r in result["courses"]} == {"every", "odd", "specific"}
    assert client.get("/api/calendar?date=2027-02-01", headers=HEADERS).json()["courses"] == []


def test_today_uses_configured_timezone_at_midnight(client, monkeypatch):
    class Clock:
        @staticmethod
        def now(tz):
            return datetime(2026, 10, 25, 16, 30, tzinfo=timezone.utc).astimezone(tz)

    monkeypatch.setattr(semester, "datetime", Clock)
    setup_term(client)
    result = client.get("/api/calendar", headers=HEADERS).json()
    assert (result["date"], result["week"]) == ("2026-10-26", 8)
    setup_term(client, timezone="America/New_York")
    result = client.get("/api/calendar", headers=HEADERS).json()
    assert (result["date"], result["week"]) == ("2026-10-25", 7)


@pytest.mark.parametrize(
    "resource,payload,change,event",
    [
        ("tasks", {"title": "before"}, {"done": True}, "task"),
        ("courses", COURSE, {"name": "after"}, "course"),
    ],
)
def test_update_delete_two_clients(client, resource, payload, change, event):
    row = client.post("/api/" + resource, headers=HEADERS, json=payload).json()
    url = f"/api/{resource}/{row['id']}"
    with client.websocket_connect("/ws?token=test-token") as first:
        with client.websocket_connect("/ws?token=test-token") as second:
            assert client.put(url, headers=HEADERS, json=change).status_code == 200
            received = first.receive_json()
            assert received == second.receive_json()
            assert received["type"] == event + ".updated"
            assert received["data"]["id"] == row["id"]
            assert client.delete(url, headers=HEADERS).status_code == 204
            received = first.receive_json()
            assert received == second.receive_json()
            assert received["type"] == event + ".deleted"
            assert client.get("/api/" + resource, headers=HEADERS).json() == []


def test_semester_event_and_push_failure(client, monkeypatch):
    with client.websocket_connect("/ws?token=test-token") as socket:
        setup_term(client)
        assert socket.receive_json()["type"] == "semester.updated"
    monkeypatch.setattr(app.state.push_service, "broadcast", AsyncMock(side_effect=RuntimeError))
    setup_term(client, total_weeks=20)
    assert semester.get_settings()["settings"]["total_weeks"] == 20


def test_rollback_emits_nothing(client, monkeypatch):
    setup_term(client)
    notify = AsyncMock()
    monkeypatch.setattr(app.state.push_service, "notify", notify)
    with db._conn() as conn:
        conn.execute(
            "CREATE TRIGGER fail_settings BEFORE UPDATE ON semester_settings BEGIN SELECT RAISE(ABORT,'test rollback'); END"
        )
    import sqlite3

    with pytest.raises(sqlite3.IntegrityError):
        client.put("/api/semester", headers=HEADERS, json={**SETTINGS, "total_weeks": 20})
    assert semester.get_settings()["settings"]["total_weeks"] == 18
    notify.assert_not_awaited()


def test_missing_mutations_emit_nothing(client, monkeypatch):
    notify = AsyncMock()
    monkeypatch.setattr(app.state.push_service, "notify", notify)
    for resource in ("tasks", "courses"):
        assert client.put(f"/api/{resource}/999", headers=HEADERS, json={}).status_code == 404
        assert client.delete(f"/api/{resource}/999", headers=HEADERS).status_code == 404
    notify.assert_not_awaited()
