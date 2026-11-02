"""B8 通用账号、设备会话和备份优先的版本三迁移。"""

import hashlib
import secrets
import sqlite3
import time
from contextlib import closing
from uuid import uuid4

from . import config, db

DEFAULT_USER = 1


def backup_before_upgrade(version=3, label="b8"):
    """旧库先创建唯一备份；失败则停止升级，不覆盖原有备份。"""
    path = config.DB_PATH
    if not path.exists() or not path.stat().st_size:
        return None
    with closing(sqlite3.connect(path)) as source:
        tables = {r[0] for r in source.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if (
            "schema_migrations" in tables
            and source.execute(
                "SELECT 1 FROM schema_migrations WHERE version=?", (version,)
            ).fetchone()
        ):
            return None
        backup = path.with_name(f"{path.stem}.pre-{label}-{uuid4().hex}.db")
        with backup.open("xb"):
            pass
        backup.chmod(0o600)
        deadline = time.monotonic() + config.DB_BACKUP_TIMEOUT_SECONDS

        def progress(*_args):
            if time.monotonic() > deadline:
                raise TimeoutError("B8 backup timed out")

        with closing(sqlite3.connect(backup)) as target:
            source.backup(target, pages=128, progress=progress)
            if target.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise RuntimeError("B8 backup integrity check failed")
        return backup


def migrate(conn):
    """在调用者事务内回填默认用户；微信身份独立关联，不猜测历史共享数据归属。"""
    if conn.execute("SELECT 1 FROM schema_migrations WHERE version=3").fetchone():
        return
    conn.execute(
        "CREATE TABLE users (id INTEGER PRIMARY KEY AUTOINCREMENT, created_at REAL NOT NULL)"
    )
    conn.execute("INSERT INTO users(id,created_at) VALUES (1,?)", (time.time(),))
    conn.execute(
        "ALTER TABLE wechat_users ADD COLUMN business_user_id INTEGER REFERENCES users(id)"
    )
    for row in conn.execute("SELECT id FROM wechat_users").fetchall():
        uid = conn.execute("INSERT INTO users(created_at) VALUES (?)", (time.time(),)).lastrowid
        conn.execute("UPDATE wechat_users SET business_user_id=? WHERE id=?", (uid, row[0]))
    for table in ("courses", "tasks", "reminders"):
        conn.execute(
            f"ALTER TABLE {table} ADD COLUMN user_id INTEGER NOT NULL DEFAULT 1 REFERENCES users(id)"
        )
        conn.execute(f"CREATE INDEX {table}_owner ON {table}(user_id,id)")
    conn.execute("UPDATE semester_settings SET scope='user:1' WHERE scope='shared'")
    conn.execute(
        "UPDATE wechat_subscriptions SET status='cancelled',last_error='b8_ownership_migration' WHERE status IN ('pending','retry','sending')"
    )
    conn.execute(
        "CREATE TABLE device_sessions (token_hash TEXT PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id), expires_at REAL NOT NULL)"
    )
    conn.execute(
        "CREATE TABLE device_pairings (code_hash TEXT PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id), expires_at REAL NOT NULL)"
    )
    conn.execute(
        "INSERT INTO schema_migrations VALUES (3,?)", (config.REMINDER_NAIVE_OFFSET_MINUTES,)
    )


def digest(token):
    return hashlib.sha256(token.encode()).hexdigest()


def wechat_owner(wx_id):
    with db._conn() as conn:
        row = conn.execute(
            "SELECT business_user_id FROM wechat_users WHERE id=?", (wx_id,)
        ).fetchone()
    return row[0] if row else None


def session_user(token):
    """先验设备会话，再复用微信摘要、有效期及 AppID 校验。"""
    from . import wechat_store

    if not token or len(token) > 256:
        return None
    with db._conn() as conn:
        row = conn.execute(
            "SELECT user_id FROM device_sessions WHERE token_hash=? AND expires_at>?",
            (digest(token), time.time()),
        ).fetchone()
    if row:
        return row[0]
    wx_id = wechat_store.session_user(token)
    return wechat_owner(wx_id) if wx_id is not None else None


def pair(user_id):
    code = secrets.token_urlsafe(24)
    with db._conn() as conn:
        conn.execute("DELETE FROM device_pairings WHERE expires_at<=?", (time.time(),))
        conn.execute(
            "INSERT INTO device_pairings VALUES (?,?,?)", (digest(code), user_id, time.time() + 300)
        )
    return {"pairing_code": code, "expires_in": 300}


def device_session(code=None):
    """API Key 仅能签发默认演示用户；私有用户由短期一次性配对码确定。"""
    token = secrets.token_urlsafe(32)
    with db._conn() as conn:
        conn.execute("BEGIN IMMEDIATE")
        user_id = DEFAULT_USER
        if code is not None:
            row = conn.execute(
                "SELECT user_id FROM device_pairings WHERE code_hash=? AND expires_at>?",
                (digest(code), time.time()),
            ).fetchone()
            if row is None:
                raise ValueError("pairing_invalid")
            user_id = row[0]
            conn.execute("DELETE FROM device_pairings WHERE code_hash=?", (digest(code),))
        conn.execute("DELETE FROM device_sessions WHERE expires_at<=?", (time.time(),))
        conn.execute(
            "INSERT INTO device_sessions VALUES (?,?,?)",
            (digest(token), user_id, time.time() + config.DEVICE_SESSION_TTL_SECONDS),
        )
    return {
        "user_id": user_id,
        "device_token": token,
        "token_type": "Bearer",
        "expires_in": config.DEVICE_SESSION_TTL_SECONDS,
    }


def revoke(token):
    with db._conn() as conn:
        conn.execute("DELETE FROM device_sessions WHERE token_hash=?", (digest(token),))
        conn.execute("DELETE FROM wechat_sessions WHERE token_hash=?", (digest(token),))
