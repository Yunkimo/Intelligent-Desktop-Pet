"""固定时钟覆盖领取、故障窗口、迁移、取消与时间契约。"""

import asyncio
import sqlite3
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from app import config, db, reminder_store
from app.main import app
from app.reminder_time import normalize_reminder_time, utc_text
from app.scheduler import Scheduler
from fastapi.testclient import TestClient

NOW = datetime(2040, 1, 1, tzinfo=timezone.utc).timestamp()


def reminder(when=NOW, channel="pc"):
    return db.create_reminder("提醒", utc_text(when), channel=channel)


def test_exact_due_boundary_and_repeat_scan(client):
    async def scenario():
        item = reminder(NOW + 1)
        clock = [NOW]
        send = AsyncMock(return_value=1)
        scheduler = Scheduler(send, lambda: clock[0])
        assert await scheduler.run_once() == 0
        clock[0] += 1
        assert await scheduler.run_once() == 1
        assert await scheduler.run_once() == 0
        event = send.await_args.args[0]
        assert event["type"] == "reminder.due"
        assert event["data"] == {"id": item["id"]}
        assert db.list_reminders()[0]["done"] == 1
        assert reminder_store.delivery_status(item["id"])["status"] == "sent"

    asyncio.run(scenario())


def test_retry_limit_backoff_and_stable_event(client):
    async def scenario():
        item = reminder()
        clock = [NOW]
        send = AsyncMock(return_value=0)
        scheduler = Scheduler(send, lambda: clock[0])
        assert await scheduler.run_once() == 1
        assert await scheduler.run_once() == 0
        clock[0] += 29.9
        assert await scheduler.run_once() == 0
        clock[0] = NOW + 30
        assert await scheduler.run_once() == 1
        clock[0] = NOW + 90
        assert await scheduler.run_once() == 1
        status = reminder_store.delivery_status(item["id"])
        assert status["status"] == "failed"
        assert status["attempts"] == 3
        assert status["last_error"] == "no_clients"
        assert db.list_reminders()[0]["done"] == 0
        events = [call.args[0] for call in send.await_args_list]
        assert events[0] == events[1] == events[2]
        clock[0] += 1000
        assert await scheduler.run_once() == 0
        db.update_reminder(item["id"], {"done": False})
        assert reminder_store.delivery_status(item["id"])["event_id"] != status["event_id"]

    asyncio.run(scenario())


@pytest.mark.parametrize("error", [RuntimeError("sensitive upstream data"), OSError("broken")])
def test_send_failure_never_marks_done(client, error, caplog):
    item = reminder()
    scheduler = Scheduler(AsyncMock(side_effect=error), lambda: NOW)
    asyncio.run(scheduler.run_once())
    assert reminder_store.delivery_status(item["id"])["last_error"] == "send_failed"
    assert db.list_reminders()[0]["done"] == 0
    assert "sensitive upstream data" not in caplog.text


def test_send_timeout_is_bounded(client, monkeypatch):
    async def scenario():
        async def blocked(_event):
            await asyncio.Event().wait()

        item = reminder()
        monkeypatch.setattr(config, "SCHEDULER_SEND_TIMEOUT_SECONDS", 0.01)
        await asyncio.wait_for(Scheduler(blocked, lambda: NOW).run_once(), 1)
        assert reminder_store.delivery_status(item["id"])["last_error"] == "send_timeout"

    asyncio.run(scenario())


def test_restart_after_claim_reuses_event_and_rejects_stale_completion(client):
    item = reminder()
    first = reminder_store.claim_due(NOW)
    assert reminder_store.claim_due(NOW + config.SCHEDULER_LEASE_SECONDS - 0.1) is None
    second = reminder_store.claim_due(NOW + config.SCHEDULER_LEASE_SECONDS)
    assert first["event_id"] == second["event_id"]
    assert first["claim_token"] != second["claim_token"]
    assert not reminder_store.finish(first, NOW + 30, None)
    assert reminder_store.finish(second, NOW + 30, None)
    assert reminder_store.delivery_status(item["id"])["attempts"] == 2


def test_crash_after_send_before_commit_may_repeat_same_event(client, monkeypatch):
    async def scenario():
        item = reminder()
        original = reminder_store.finish

        def crash(*args):
            raise sqlite3.OperationalError("simulated crash before status commit")

        send = AsyncMock(return_value=1)
        monkeypatch.setattr(reminder_store, "finish", crash)
        with pytest.raises(sqlite3.OperationalError):
            await Scheduler(send, lambda: NOW).run_once()
        assert db.list_reminders()[0]["done"] == 0
        monkeypatch.setattr(reminder_store, "finish", original)
        await Scheduler(send, lambda: NOW + config.SCHEDULER_LEASE_SECONDS).run_once()
        assert send.await_args_list[0].args[0] == send.await_args_list[1].args[0]
        assert reminder_store.delivery_status(item["id"])["status"] == "sent"
        assert db.list_reminders()[0]["done"] == 1

    asyncio.run(scenario())


def test_crash_on_final_attempt_stops_after_lease(client, monkeypatch):
    item = reminder()
    monkeypatch.setattr(config, "SCHEDULER_MAX_ATTEMPTS", 1)
    assert reminder_store.claim_due(NOW)
    assert reminder_store.claim_due(NOW + config.SCHEDULER_LEASE_SECONDS) is None
    status = reminder_store.delivery_status(item["id"])
    assert status["status"] == "failed"
    assert status["last_error"] == "attempts_exhausted"
    assert db.list_reminders()[0]["done"] == 0


def test_atomic_claim_across_connections(client):
    reminder()
    with ThreadPoolExecutor(max_workers=4) as pool:
        claims = list(pool.map(reminder_store.claim_due, [NOW] * 4))
    assert sum(claim is not None for claim in claims) == 1


def test_concurrent_scans_and_batch_limit(client, monkeypatch):
    async def scenario():
        for _ in range(3):
            reminder()
        monkeypatch.setattr(config, "SCHEDULER_BATCH_SIZE", 1)
        send = AsyncMock(return_value=1)
        scheduler = Scheduler(send, lambda: NOW)
        assert await asyncio.gather(scheduler.run_once(), scheduler.run_once()) == [1, 1]
        assert len({call.args[0]["data"]["id"] for call in send.await_args_list}) == 2
        assert sum(row["done"] for row in db.list_reminders()) == 2

    asyncio.run(scenario())


def test_edit_and_delete_invalidate_inflight_claims(client):
    item = reminder()
    old = reminder_store.claim_due(NOW)
    updated = db.update_reminder(item["id"], {"remind_at": utc_text(NOW + 60)})
    assert updated["done"] == 0
    assert not reminder_store.is_current(old)
    assert not reminder_store.finish(old, NOW, None)
    assert reminder_store.claim_due(NOW) is None
    new = reminder_store.claim_due(NOW + 60)
    assert new["event_id"] != old["event_id"]
    assert db.delete_reminder(item["id"])
    assert not reminder_store.is_current(new)
    assert not reminder_store.finish(new, NOW + 60, None)
    assert reminder_store.delivery_status(item["id"]) is None


def test_phone_waits_for_b3_manual_done_and_past_due_recovery(client):
    phone = reminder(NOW - 100, "phone")
    done = reminder(NOW - 100)
    db.update_reminder(done["id"], {"done": True})
    overdue = reminder(NOW - 100, "both")
    asyncio.run(Scheduler(AsyncMock(return_value=1), lambda: NOW).run_once())
    states = {item["id"]: item["done"] for item in db.list_reminders()}
    assert states == {phone["id"]: 0, done["id"]: 1, overdue["id"]: 1}
    assert reminder_store.delivery_status(phone["id"])["attempts"] == 0
    assert reminder_store.delivery_status(done["id"])["status"] == "cancelled"


def test_cancel_while_sending_leaves_recoverable_lease(client):
    async def scenario():
        item = reminder()
        entered = asyncio.Event()

        async def blocked(_event):
            entered.set()
            await asyncio.Event().wait()

        scheduler = Scheduler(blocked, lambda: NOW)
        scheduler.start()
        original_task = scheduler._task
        scheduler.start()
        assert scheduler._task is original_task
        await asyncio.wait_for(entered.wait(), 1)
        await asyncio.wait_for(scheduler.stop(), 1)
        await scheduler.stop()
        assert reminder_store.delivery_status(item["id"])["status"] == "sending"
        assert db.list_reminders()[0]["done"] == 0
        send = AsyncMock(return_value=1)
        assert await Scheduler(send, lambda: NOW + 30).run_once() == 1

    asyncio.run(scenario())


def test_locked_database_does_not_block_event_loop_and_recovers(client, monkeypatch):
    async def scenario():
        item = reminder()
        monkeypatch.setattr(config, "DB_TIMEOUT_SECONDS", 0.05)
        monkeypatch.setattr(config, "SCHEDULER_INTERVAL_SECONDS", 0.01)
        loop = asyncio.get_running_loop()
        lock_failed = asyncio.Event()
        committed = asyncio.Event()
        original_claim = reminder_store.claim_due
        original_finish = reminder_store.finish

        def observe_claim(now):
            try:
                return original_claim(now)
            except sqlite3.OperationalError as exc:
                if "locked" in str(exc):
                    loop.call_soon_threadsafe(lock_failed.set)
                raise

        def observe_finish(claim, now, error):
            changed = original_finish(claim, now, error)
            if changed and error is None:
                loop.call_soon_threadsafe(committed.set)
            return changed

        monkeypatch.setattr(reminder_store, "claim_due", observe_claim)
        monkeypatch.setattr(reminder_store, "finish", observe_finish)
        conn = sqlite3.connect(config.DB_PATH)
        conn.execute("BEGIN IMMEDIATE")
        scheduler = Scheduler(AsyncMock(return_value=1), lambda: NOW)
        scheduler.start()
        try:
            ticks = 0
            for _ in range(10):
                await asyncio.sleep(0.01)
                ticks += 1
            assert ticks == 10
            await asyncio.wait_for(lock_failed.wait(), 2)
            assert (
                conn.execute("SELECT done FROM reminders WHERE id=?", (item["id"],)).fetchone()[0]
                == 0
            )
            conn.rollback()
            # 等真实事务提交后停掉扫描，再读库；观察者不参与 50ms 锁竞争。
            await asyncio.wait_for(committed.wait(), 2)
        finally:
            conn.close()
            await scheduler.stop()
        assert db.list_reminders()[0]["done"] == 1
        assert reminder_store.delivery_status(item["id"])["status"] == "sent"

    asyncio.run(scenario())


def test_lifespan_starts_and_stops_scheduler(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "lifecycle.db")
    monkeypatch.setattr(config, "SCHEDULER_ENABLED", True)
    with TestClient(app):
        task = app.state.scheduler._task
        assert task is not None
    assert task.done()
    assert app.state.scheduler._task is None


@pytest.mark.parametrize(
    "value", ["2040-01-01T08:00:00+08:00", "2040-01-01T00:00:00Z", "2040-01-01T08:00:00"]
)
def test_timezone_normalization(value):
    assert normalize_reminder_time(value) == "2040-01-01T00:00:00.000000+00:00"


@pytest.mark.parametrize("value", ["bad", "2040-01-01", "2040-13-01T00:00", None])
def test_invalid_reminder_input_returns_422(client, value):
    response = client.post(
        "/api/reminders",
        json={"title": "测试", "remind_at": value},
        headers={"X-API-Key": "test-token"},
    )
    assert response.status_code == 422


@pytest.mark.parametrize("field", ["title", "body", "remind_at", "done", "channel"])
def test_invalid_null_update_returns_422(client, field):
    item = reminder()
    response = client.put(
        f"/api/reminders/{item['id']}", json={field: None}, headers={"X-API-Key": "test-token"}
    )
    assert response.status_code == 422


def test_delivery_diagnostics_require_auth(client):
    item = reminder()
    path = f"/api/reminders/{item['id']}/delivery"
    assert client.get(path).status_code == 401
    result = client.get(path, headers={"X-API-Key": "test-token"})
    assert result.json()["status"] == "pending"
    assert "claim_token" not in result.json()
    assert (
        client.get("/api/reminders/999/delivery", headers={"X-API-Key": "test-token"}).status_code
        == 404
    )


def test_migration_backup_idempotence_invalid_legacy_data(tmp_path, monkeypatch):
    path = tmp_path / "legacy.db"
    monkeypatch.setattr(config, "DB_PATH", path)
    conn = sqlite3.connect(path)
    conn.executescript(db._SCHEMA)
    conn.executemany(
        "INSERT INTO reminders(title,remind_at,done) VALUES (?,?,?)",
        [
            ("旧提醒", "2040-01-01T08:00:00", 0),
            ("坏时间", "bad", 0),
            ("已完成", "2040-01-01T08:00:00", 1),
        ],
    )
    conn.commit()
    conn.close()
    db.init_db()
    event_id = reminder_store.delivery_status(1)["event_id"]
    db.init_db()
    assert reminder_store.delivery_status(1)["event_id"] == event_id
    assert reminder_store.delivery_status(2)["last_error"] == "invalid_remind_at"
    assert reminder_store.delivery_status(3)["status"] == "cancelled"
    backups = list(tmp_path.glob("legacy.pre-b2-*.db"))
    assert len(backups) == 1
    with closing(sqlite3.connect(backups[0])) as backup:
        assert (
            backup.execute("SELECT remind_at FROM reminders WHERE id=1").fetchone()[0]
            == "2040-01-01T08:00:00"
        )
    assert db.list_reminders()[0]["remind_at"].endswith("+00:00")


def test_migration_failure_rolls_back_and_can_retry(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "rollback.db")
    conn = sqlite3.connect(config.DB_PATH)
    conn.executescript(db._SCHEMA)
    conn.execute("INSERT INTO reminders(title,remind_at) VALUES ('test','2040-01-01T08:00')")
    conn.commit()
    conn.close()
    original = reminder_store.seed_delivery

    def broken(conn, row):
        original(conn, row)
        raise RuntimeError("migration interrupted")

    monkeypatch.setattr(reminder_store, "seed_delivery", broken)
    with pytest.raises(RuntimeError):
        db.init_db()
    with closing(sqlite3.connect(config.DB_PATH)) as check:
        assert check.execute("SELECT count(*) FROM schema_migrations").fetchone()[0] == 0
        assert check.execute("SELECT remind_at FROM reminders").fetchone()[0] == "2040-01-01T08:00"
    monkeypatch.setattr(reminder_store, "seed_delivery", original)
    db.init_db()
    assert reminder_store.delivery_status(1)["status"] == "pending"


def test_backup_script_refuses_overwrite_and_restores_to_new_path(client, tmp_path):
    item = reminder()
    script = Path(__file__).resolve().parents[2] / "scripts" / "backup_backend_db.py"
    backup = tmp_path / "backup.db"
    restored = tmp_path / "restored.db"
    for source, target in ((config.DB_PATH, backup), (backup, restored)):
        result = subprocess.run(
            [sys.executable, str(script), str(source), str(target)],
            capture_output=True,
            timeout=10,
        )
        assert result.returncode == 0
    again = subprocess.run(
        [sys.executable, str(script), str(config.DB_PATH), str(backup)],
        capture_output=True,
        timeout=10,
    )
    assert again.returncode != 0
    with closing(sqlite3.connect(restored)) as conn:
        assert conn.execute("SELECT id FROM reminders").fetchone()[0] == item["id"]


def test_edit_between_claim_and_send_skips_superseded_notification(client, monkeypatch):
    item = reminder()
    original = reminder_store.is_current

    def edit_before_check(claim):
        db.update_reminder(item["id"], {"remind_at": utc_text(NOW + 100)})
        return original(claim)

    monkeypatch.setattr(reminder_store, "is_current", edit_before_check)
    send = AsyncMock(return_value=1)
    assert asyncio.run(Scheduler(send, lambda: NOW).run_once()) == 0
    send.assert_not_awaited()


def test_reschedule_api_normalizes_time_and_changes_event(client):
    item = reminder()
    old_event = reminder_store.delivery_status(item["id"])["event_id"]
    headers = {"X-API-Key": "test-token"}
    response = client.put(
        f"/api/reminders/{item['id']}",
        json={"remind_at": "2040-01-02T08:00:00+08:00"},
        headers=headers,
    )
    assert response.status_code == 200
    assert response.json()["remind_at"] == "2040-01-02T00:00:00.000000+00:00"
    assert reminder_store.delivery_status(item["id"])["event_id"] != old_event
