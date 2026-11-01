"""B8：真实 SQLite/HTTP/WS 用户隔离、会话和迁移边界。"""

import asyncio
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

import pytest
from app import accounts, config, db, wechat_store
from app.push_service import PushService
from app.scheduler import Scheduler
from starlette.websockets import WebSocketDisconnect

KEY = {"X-API-Key": "test-token"}
COURSE = {
    "name": "private",
    "day_of_week": 1,
    "start_time": "08:00",
    "end_time": "09:00",
    "weeks": [1],
}
DUE = "2040-01-01T08:00:00+08:00"


def identity(name):
    result = wechat_store.new_session(name)
    return (
        result["account_id"],
        {"Authorization": "Bearer " + result["session_token"]},
        result["session_token"],
    )


@pytest.mark.parametrize(
    "resource,payload",
    [
        ("courses", COURSE),
        ("tasks", {"title": "private", "remind_at": DUE}),
        ("reminders", {"title": "private", "channel": "pc", "remind_at": DUE}),
    ],
)
def test_two_owners_crud_and_id_probing(client, resource, payload):
    a, ha, _ = identity("alice")
    b, hb, _ = identity("bob")
    ra = client.post(f"/api/{resource}", json={**payload, "user_id": b}, headers=ha)
    rb = client.post(f"/api/{resource}", json=payload, headers=hb)
    assert ra.status_code == rb.status_code == 201
    row = ra.json()
    assert row["user_id"] == a  # 客户端不能指定归属
    assert [r["id"] for r in client.get(f"/api/{resource}", headers=hb).json()] == [rb.json()["id"]]
    path = f"/api/{resource}/{row['id']}"
    assert client.get(path, headers=ha).status_code == 200
    for outsider in (hb, KEY):
        assert client.get(path, headers=outsider).status_code == 404
        assert client.put(path, headers=outsider, json={}).status_code == 404
        assert client.delete(path, headers=outsider).status_code == 404
    assert client.delete(path, headers=ha).status_code == 204
    assert client.get(path, headers=ha).status_code == 404


def test_associated_reminders_cannot_cross_owner(client):
    a, ha, _ = identity("a")
    b, hb, _ = identity("b")
    task = client.post("/api/tasks", headers=ha, json={"title": "a", "remind_at": DUE}).json()
    rid = client.get("/api/reminders", headers=ha).json()[0]["id"]
    assert client.get(f"/api/reminders/{rid}/delivery", headers=hb).status_code == 404
    assert (
        client.post(
            "/api/reminders",
            headers=hb,
            json={"title": "x", "remind_at": DUE, "task_id": task["id"]},
        ).status_code
        == 404
    )
    own = client.post("/api/reminders", headers=hb, json={"title": "b", "remind_at": DUE}).json()
    assert (
        client.put(
            f"/api/reminders/{own['id']}", headers=hb, json={"task_id": task["id"]}
        ).status_code
        == 404
    )
    assert (
        client.post("/api/wechat/reminders", headers=hb, json={"task_id": task["id"]}).status_code
        == 404
    )
    assert (
        client.post("/api/wechat/reminders", headers=ha, json={"task_id": task["id"]}).status_code
        == 200
    )
    assert client.delete(f"/api/tasks/{task['id']}", headers=hb).status_code == 404
    assert len(db.list_reminders(a)) == 2
    assert client.delete(f"/api/tasks/{task['id']}", headers=ha).status_code == 204
    assert db.list_reminders(a) == [] and len(db.list_reminders(b)) == 1


def test_bulk_calendar_and_settings_are_private(client):
    _, ha, _ = identity("a")
    _, hb, _ = identity("b")
    settings = {"start_date": "2026-09-07", "total_weeks": 18, "timezone": "Asia/Shanghai"}
    assert client.put("/api/semester", headers=ha, json=settings).status_code == 200
    assert client.get("/api/semester", headers=hb).json()["configured"] is False
    assert (
        client.post("/api/courses/bulk", headers=ha, json={"courses": [COURSE, COURSE]}).status_code
        == 201
    )
    assert len(client.get("/api/calendar?date=2026-09-07", headers=ha).json()["courses"]) == 2
    client.put("/api/semester", headers=hb, json=settings)
    assert client.get("/api/calendar?date=2026-09-07", headers=hb).json()["courses"] == []
    assert client.get("/api/courses", headers=KEY).json() == []


def test_auth_precedence_and_secure_mode(client, monkeypatch):
    _, ha, token = identity("a")
    assert client.get("/api/tasks").status_code == 401
    assert (
        client.get("/api/tasks", headers={**KEY, "Authorization": "Bearer wrong"}).status_code
        == 401
    )
    monkeypatch.setattr(config, "ALLOW_LEGACY_API_KEY", False)
    assert client.get("/api/tasks", headers=KEY).status_code == 401
    assert client.get("/api/tasks", headers=ha).status_code == 200
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect("/ws?token=test-token"):
            pass
    with db._conn() as conn:
        conn.execute("UPDATE wechat_sessions SET expires_at=0")
    assert client.get("/api/tasks", headers=ha).status_code == 401
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect("/ws?token=" + token):
            pass


def test_pairing_device_expiry_and_revocation(client):
    a, ha, _ = identity("a")
    pairing = client.post("/api/auth/pairing", headers=ha).json()
    result = client.post("/api/auth/device", json={"pairing_code": pairing["pairing_code"]})
    assert result.status_code == 200 and result.headers["cache-control"] == "no-store"
    device = result.json()
    assert device["user_id"] == a
    hd = {"Authorization": "Bearer " + device["device_token"]}
    assert client.get("/api/auth/me", headers=hd).json() == {"user_id": a}
    assert (
        client.post("/api/auth/device", json={"pairing_code": pairing["pairing_code"]}).status_code
        == 401
    )
    assert client.post("/api/auth/device", json={"user_id": a}, headers=KEY).status_code == 422
    default = client.post("/api/auth/device", json={}, headers=KEY).json()
    assert default["user_id"] == 1
    assert client.post("/api/auth/device", json={}).status_code == 401
    with db._conn() as conn:
        hashes = str([tuple(r) for r in conn.execute("SELECT * FROM device_sessions")])
        assert device["device_token"] not in hashes and pairing["pairing_code"] not in hashes
    assert client.post("/api/auth/logout", headers=hd).status_code == 204
    assert client.get("/api/tasks", headers=hd).status_code == 401
    with db._conn() as conn:
        conn.execute("UPDATE device_sessions SET expires_at=0")
    assert accounts.session_user(default["device_token"]) is None
    code = accounts.pair(a)["pairing_code"]
    with db._conn() as conn:
        conn.execute("UPDATE device_pairings SET expires_at=0")
    assert client.post("/api/auth/device", json={"pairing_code": code}).status_code == 401


def test_pairing_concurrent_consume_once(client):
    a, _, _ = identity("a")
    code = accounts.pair(a)["pairing_code"]

    def redeem(_):
        try:
            return accounts.device_session(code)["user_id"]
        except ValueError:
            return None

    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(redeem, range(8)))
    assert results.count(a) == 1 and results.count(None) == 7


def test_websocket_routes_never_mix_users(client):
    _, ha, ta = identity("a")
    _, hb, tb = identity("b")
    with (
        client.websocket_connect("/ws?token=" + ta) as wa,
        client.websocket_connect("/ws?token=" + tb) as wb,
    ):
        a = client.post("/api/tasks", headers=ha, json={"title": "a"}).json()
        b = client.post("/api/tasks", headers=hb, json={"title": "b"}).json()
        assert wa.receive_json()["data"]["id"] == a["id"]
        assert wb.receive_json()["data"]["id"] == b["id"]
        client.delete("/api/tasks/" + str(a["id"]), headers=ha)
        client.delete("/api/tasks/" + str(b["id"]), headers=hb)
        assert wa.receive_json()["type"] == "task.deleted"
        assert wb.receive_json()["type"] == "task.deleted"
        client.post("/api/auth/logout", headers=ha)
        client.post("/api/tasks", headers=hb, json={"title": "b2"})
        with pytest.raises(WebSocketDisconnect):
            wa.receive_json()
        assert wb.receive_json()["type"] == "task.created"


def test_scheduler_delivers_only_to_owner(client):
    a, _, _ = identity("a")
    b, _, _ = identity("b")

    class Socket:
        def __init__(self):
            self.events = []

        async def accept(self):
            pass

        async def send_text(self, message):
            self.events.append(message)

        async def close(self, code):
            pass

    async def run():
        service = PushService(1, 1)
        sa, sb = Socket(), Socket()
        await service.connect(sa, a)
        await service.connect(sb, b)
        db.create_reminder("private", "2020-01-01T00:00:00Z", channel="pc", user_id=a)
        await Scheduler(service.broadcast).run_once()
        assert len(sa.events) == 1 and sb.events == []

    asyncio.run(run())


def test_legacy_upgrade_backup_repeat_and_rollback(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "old.db")
    # 创建与当前 develop 相同的迁移前结构，保留真实旧数据及学期设置。
    with patch.object(accounts, "migrate", lambda conn: None):
        db.init_db()
    with sqlite3.connect(config.DB_PATH) as conn:
        conn.execute(
            "INSERT INTO courses(name,day_of_week,start_time,end_time) VALUES ('old',1,'08:00','09:00')"
        )
        conn.execute("INSERT INTO tasks(title,created_at) VALUES ('old','2026-01-01')")
        conn.execute(
            "INSERT INTO semester_settings VALUES ('shared','2026-09-07',18,'Asia/Shanghai')"
        )
    real = accounts.migrate

    def fail(conn):
        real(conn)
        raise RuntimeError("injected")

    with patch.object(accounts, "migrate", fail), pytest.raises(RuntimeError):
        db.init_db()
    with sqlite3.connect(config.DB_PATH) as conn:
        assert "user_id" not in {r[1] for r in conn.execute("PRAGMA table_info(tasks)")}
        assert conn.execute("SELECT title FROM tasks").fetchone()[0] == "old"
    db.init_db()
    backups = list(tmp_path.glob("old.pre-b8-*.db"))
    assert backups
    with sqlite3.connect(backups[-1]) as conn:
        assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert conn.execute("SELECT title FROM tasks").fetchone()[0] == "old"
    db.init_db()
    assert list(tmp_path.glob("old.pre-b8-*.db")) == backups
    assert db.list_tasks()[0]["user_id"] == 1
    with db._conn() as conn:
        assert not conn.execute("PRAGMA foreign_key_check").fetchall()
        assert conn.execute("SELECT scope FROM semester_settings").fetchone()[0] == "user:1"
        assert (
            conn.execute("SELECT COUNT(*) FROM schema_migrations WHERE version=3").fetchone()[0]
            == 1
        )


def test_backup_failure_blocks_upgrade(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "old.db")
    with sqlite3.connect(config.DB_PATH) as conn:
        conn.execute("CREATE TABLE sentinel(value TEXT)")
    with (
        patch.object(accounts, "backup_before_upgrade", side_effect=OSError("no space")),
        pytest.raises(OSError),
    ):
        db.init_db()
    with sqlite3.connect(config.DB_PATH) as conn:
        assert conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall() == [
            ("sentinel",)
        ]
