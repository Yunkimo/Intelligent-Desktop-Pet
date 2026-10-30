"""B5：真实 SQLite 事务、路由和调度；外部渠道不发送真实消息。"""

import asyncio
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from unittest.mock import AsyncMock

import pytest
from app import db, reminder_store
from app.scheduler import Scheduler
from test_c3_recovery import prepare
from test_wechat import HEADERS, dispatch
from test_wechat import wx_app as wx_app  # noqa: F401
from test_wechat import wx_config as wx_config  # noqa: F401

DUE = "2040-01-01T00:00:00+00:00"
NOW = datetime.fromisoformat(DUE).timestamp()


def test_create_atomic_and_legacy_client_replay(client):
    task = client.post("/api/tasks", headers=HEADERS, json={"title": "B5", "remind_at": DUE}).json()
    reminder = db.list_reminders()[0]
    assert reminder["channel"] == "pc"
    assert reminder["task_id"] == task["id"]
    with ThreadPoolExecutor(max_workers=4) as pool:
        rows = list(
            pool.map(lambda _: db.create_reminder("B5", DUE, task_id=task["id"]), range(12))
        )
    assert {r["id"] for r in rows} == {reminder["id"]}
    assert len(db.list_reminders()) == 1


def test_insert_failure_rolls_back(client, monkeypatch):
    def fail(*args):
        raise RuntimeError("injected")

    monkeypatch.setattr(reminder_store, "seed_delivery", fail)
    with pytest.raises(RuntimeError):
        db.create_task("B5", remind_at=DUE)
    assert db.list_tasks() == db.list_reminders() == []


@pytest.mark.parametrize("action", ["clear", "complete", "delete"])
def test_cancel_invalidates_claim_and_preserves_independent(client, action):
    task = db.create_task("B5", remind_at=DUE)
    rid = db.list_reminders()[0]["id"]
    claim = reminder_store.claim_due(NOW)
    independent = db.create_reminder("independent", DUE, channel="pc")
    if action == "delete":
        db.delete_task(task["id"])
    else:
        db.update_task(task["id"], {"remind_at": None} if action == "clear" else {"done": True})
    assert not reminder_store.is_current(claim)
    assert not reminder_store.finish(claim, NOW, None)
    next_claim = reminder_store.claim_due(NOW)
    assert next_claim["reminder_id"] == independent["id"]
    assert next_claim["reminder_id"] != rid
    assert reminder_store.claim_due(NOW) is None


def test_reschedule_content_noop_and_real_scheduler(client):
    task = db.create_task("before", remind_at=DUE)
    rid = db.list_reminders()[0]["id"]
    old = reminder_store.delivery_status(rid)["event_id"]
    db.update_task(task["id"], {"remind_at": "2040-01-01T08:00:00+08:00", "done": False})
    assert reminder_store.delivery_status(rid)["event_id"] == old
    db.update_task(
        task["id"], {"remind_at": "2040-01-02T00:00:00Z", "title": "after", "note": "body"}
    )
    assert db.list_reminders()[0]["title"] == "after"
    assert db.list_reminders()[0]["body"] == "body"
    assert reminder_store.delivery_status(rid)["event_id"] != old
    send = AsyncMock(return_value=1)
    scheduler = Scheduler(send, lambda: NOW)
    assert asyncio.run(scheduler.run_once()) == 0
    scheduler.clock = lambda: NOW + 86400
    assert asyncio.run(scheduler.run_once()) == 1
    assert asyncio.run(scheduler.run_once()) == 0
    assert send.call_count == 1
    sent_event = reminder_store.delivery_status(rid)["event_id"]
    db.update_task(task["id"], {"title": "after sending"})
    assert reminder_store.delivery_status(rid)["event_id"] == sent_event


def test_reopen_and_past_time(client):
    task = db.create_task("B5", remind_at=DUE)
    rid = db.list_reminders()[0]["id"]
    db.update_task(task["id"], {"done": True})
    assert reminder_store.claim_due(NOW + 100) is None
    db.update_task(task["id"], {"done": False})
    event = reminder_store.delivery_status(rid)["event_id"]
    db.update_task(task["id"], {"done": False})
    assert reminder_store.delivery_status(rid)["event_id"] == event
    assert reminder_store.claim_due(NOW + 100)["reminder_id"] == rid


@pytest.mark.parametrize(
    "payload", [{"remind_at": "bad"}, {"title": None}, {"note": None}, {"done": None}]
)
def test_invalid_update_is_atomic(client, payload):
    task = db.create_task("B5", remind_at=DUE)
    before = db.list_reminders()
    assert client.put(f"/api/tasks/{task['id']}", headers=HEADERS, json=payload).status_code == 422
    assert db.list_tasks() == [task]
    assert db.list_reminders() == before


def test_history_not_backfilled_and_invalid_time_can_be_cleared(client):
    with db._conn() as conn:
        conn.execute("INSERT INTO tasks(title,remind_at,created_at) VALUES ('legacy','bad','old')")
    db.init_db()
    assert db.list_reminders() == []
    db.update_task(1, {"title": "still editable"})
    db.update_task(1, {"remind_at": None})
    db.update_task(1, {"remind_at": DUE})
    assert len(db.list_reminders()) == 1


def test_phone_content_requires_fresh_authorization_and_completion_blocks_ensure(wx_app):
    client, fake = wx_app
    task, reminder, _, headers, payload = prepare(client)
    assert client.post("/api/wechat/subscribe", headers=headers, json=payload).status_code == 200
    db.update_task(task["id"], {"title": "new title", "note": "new body"})
    phone = next(r for r in db.list_reminders() if r["id"] == reminder["id"])
    assert (phone["title"], phone["body"]) == ("new title", "new body")
    assert dispatch(client) == 0
    assert fake.count("/cgi-bin/message/subscribe/send") == 0
    assert client.post("/api/wechat/subscribe", headers=headers, json=payload).status_code == 409
    db.update_task(task["id"], {"done": True})
    assert (
        client.post(
            "/api/wechat/reminders", headers=headers, json={"task_id": task["id"]}
        ).status_code
        == 409
    )


def test_legacy_duplicate_desktop_converges(client):
    task = db.create_task("B5", remind_at=DUE)
    with db._conn() as conn:
        rid = conn.execute(
            "INSERT INTO reminders(title,remind_at,channel,task_id) VALUES ('legacy',?,'pc',?)",
            (DUE, task["id"]),
        ).lastrowid
        reminder_store.seed_delivery(
            conn, dict(conn.execute("SELECT * FROM reminders WHERE id=?", (rid,)).fetchone())
        )
    db.update_task(task["id"], {"note": "repair"})
    assert len(db.list_reminders()) == 1
    assert reminder_store.delivery_status(rid) is None


def test_phone_pending_cancelled_after_desktop_sent(wx_app):
    client, fake = wx_app
    task, reminder, _, headers, payload = prepare(client)
    # both 渠道允许桌面先完成、微信稍后发送，任务完成必须取消剩余渠道。
    db.update_reminder(reminder["id"], {"channel": "both"})
    payload["event_id"] = reminder_store.delivery_status(reminder["id"])["event_id"]
    assert client.post("/api/wechat/subscribe", headers=headers, json=payload).status_code == 200
    with db._conn() as conn:
        conn.execute("UPDATE reminders SET done=1 WHERE id=?", (reminder["id"],))
    db.update_task(task["id"], {"done": True})
    assert dispatch(client) == 0
    assert fake.count("/cgi-bin/message/subscribe/send") == 0


def test_completion_failure_rolls_back_task_and_claim(client, monkeypatch):
    task = db.create_task("B5", remind_at=DUE)
    claim = reminder_store.claim_due(NOW)

    def fail(*args):
        raise RuntimeError("injected")

    monkeypatch.setattr(reminder_store, "seed_delivery", fail)
    with pytest.raises(RuntimeError):
        db.update_task(task["id"], {"done": True})
    assert db.list_tasks()[0]["done"] == 0
    assert reminder_store.is_current(claim)
