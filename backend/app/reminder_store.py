"""持久化调度领取与结果；外部发送不占用 SQLite 事务。"""

import sqlite3
import time
from contextlib import closing
from datetime import datetime
from uuid import uuid4

from . import config, db
from .reminder_time import normalize_reminder_time, utc_text


def seed_delivery(conn: sqlite3.Connection, reminder: dict) -> None:
    """为一次逻辑提醒创建稳定事件 ID；非法旧时间保留原文并记录失败。"""
    error = None
    state = "cancelled" if reminder["done"] else "pending"
    due_at = None
    try:
        normalized = normalize_reminder_time(reminder["remind_at"])
        due_at = datetime.fromisoformat(normalized).timestamp()
        conn.execute("UPDATE reminders SET remind_at=? WHERE id=?", (normalized, reminder["id"]))
    except ValueError:
        state, error = "failed", "invalid_remind_at"
    conn.execute(
        "INSERT INTO reminder_deliveries (reminder_id,event_id,due_at,status,last_error) "
        "VALUES (?,?,?,?,?)",
        (reminder["id"], str(uuid4()), due_at, state, error),
    )


def migrate(conn: sqlite3.Connection) -> None:
    """幂等迁移版本一；有旧提醒时先通过 SQLite backup 保存原库。"""
    conn.execute(
        "CREATE TABLE IF NOT EXISTS schema_migrations "
        "(version INTEGER PRIMARY KEY, legacy_offset_minutes INTEGER NOT NULL)"
    )
    if conn.execute("SELECT 1 FROM schema_migrations WHERE version=1").fetchone():
        return
    if conn.execute("SELECT 1 FROM reminders LIMIT 1").fetchone():
        backup = config.DB_PATH.with_name(f"{config.DB_PATH.stem}.pre-b2-{uuid4().hex}.db")
        partial = backup.with_suffix(".partial.db")
        deadline = time.monotonic() + config.DB_BACKUP_TIMEOUT_SECONDS

        def check_backup_progress(_status: int, _remaining: int, _total: int) -> None:
            if time.monotonic() >= deadline:
                raise TimeoutError("SQLite migration backup timed out")

        with closing(sqlite3.connect(partial)) as destination:
            conn.backup(destination, pages=128, progress=check_backup_progress, sleep=0.05)
        partial.rename(backup)
    conn.execute("BEGIN IMMEDIATE")
    # 其他初始化实例可能已完成；仍按单 worker 部署，避免覆盖迁移记录。
    if conn.execute("SELECT 1 FROM schema_migrations WHERE version=1").fetchone():
        return
    conn.execute(
        "CREATE TABLE reminder_deliveries ("
        "reminder_id INTEGER PRIMARY KEY REFERENCES reminders(id) ON DELETE CASCADE,"
        "event_id TEXT NOT NULL UNIQUE, due_at REAL, occurred_at TEXT,"
        "status TEXT NOT NULL CHECK(status IN ('pending','sending','retry','sent','failed','cancelled')),"
        "attempts INTEGER NOT NULL DEFAULT 0, next_attempt_at REAL NOT NULL DEFAULT 0,"
        "lease_until REAL NOT NULL DEFAULT 0, claim_token TEXT, last_error TEXT)"
    )
    conn.execute("CREATE INDEX delivery_due ON reminder_deliveries(status,due_at,next_attempt_at)")
    for row in conn.execute("SELECT * FROM reminders").fetchall():
        seed_delivery(conn, dict(row))
    conn.execute(
        "INSERT INTO schema_migrations VALUES (1,?)", (config.REMINDER_NAIVE_OFFSET_MINUTES,)
    )


def claim_due(now: float) -> dict | None:
    """原子领取一个到期任务；过期领取可以重试，但尝试总数有上限。"""
    with db._conn() as conn:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute(
            "UPDATE reminder_deliveries SET status='failed', claim_token=NULL, "
            "last_error='attempts_exhausted' WHERE status='sending' AND lease_until<=? AND attempts>=?",
            (now, config.SCHEDULER_MAX_ATTEMPTS),
        )
        row = conn.execute(
            "SELECT d.* FROM reminder_deliveries d JOIN reminders r ON r.id=d.reminder_id "
            "WHERE r.done=0 AND r.channel IN ('pc','both') AND d.due_at<=? AND d.attempts<? AND "
            "((d.status IN ('pending','retry') AND d.next_attempt_at<=?) "
            "OR (d.status='sending' AND d.lease_until<=?)) ORDER BY d.due_at,r.id LIMIT 1",
            (now, config.SCHEDULER_MAX_ATTEMPTS, now, now),
        ).fetchone()
        if row is None:
            return None
        claim = dict(row)
        claim.update(
            claim_token=str(uuid4()),
            attempts=row["attempts"] + 1,
            occurred_at=row["occurred_at"] or utc_text(now),
        )
        conn.execute(
            "UPDATE reminder_deliveries SET status='sending',attempts=?,claim_token=?,"
            "occurred_at=?,lease_until=? WHERE reminder_id=?",
            (
                claim["attempts"],
                claim["claim_token"],
                claim["occurred_at"],
                now + config.SCHEDULER_LEASE_SECONDS,
                claim["reminder_id"],
            ),
        )
        return claim


def is_current(claim: dict) -> bool:
    """发送前确认领取仍有效，减少编辑或删除后的过期通知。"""
    with db._conn() as conn:
        return (
            conn.execute(
                "SELECT 1 FROM reminder_deliveries d JOIN reminders r ON r.id=d.reminder_id "
                "WHERE d.claim_token=? AND d.status='sending' AND r.done=0",
                (claim["claim_token"],),
            ).fetchone()
            is not None
        )


def finish(claim: dict, now: float, error: str | None) -> bool:
    """校验领取代号后原子写结果；旧发送不能覆盖重新编辑的提醒。"""
    if error is None:
        state = "sent"
    else:
        state = "failed" if claim["attempts"] >= config.SCHEDULER_MAX_ATTEMPTS else "retry"
    delay = min(
        config.SCHEDULER_RETRY_SECONDS * 2 ** (claim["attempts"] - 1),
        config.SCHEDULER_MAX_RETRY_SECONDS,
    )
    with db._conn() as conn:
        conn.execute("BEGIN IMMEDIATE")
        result = conn.execute(
            "UPDATE reminder_deliveries SET status=?,last_error=?,next_attempt_at=?,"
            "lease_until=0,claim_token=NULL WHERE claim_token=? AND status='sending'",
            (state, error, now + delay if error else 0, claim["claim_token"]),
        )
        if result.rowcount and error is None:
            conn.execute("UPDATE reminders SET done=1 WHERE id=?", (claim["reminder_id"],))
        return result.rowcount == 1


def delivery_status(reminder_id: int) -> dict | None:
    """提供诊断状态，不暴露内部领取代号。"""
    with db._conn() as conn:
        row = conn.execute(
            "SELECT event_id,status,attempts,last_error,next_attempt_at,lease_until "
            "FROM reminder_deliveries WHERE reminder_id=?",
            (reminder_id,),
        ).fetchone()
        return dict(row) if row else None
