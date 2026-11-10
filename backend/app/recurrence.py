"""每周提醒复用持久领取；本次结果归档后推进，停用不补发。"""

from datetime import datetime, timedelta

from . import config, db

WEEK = 7 * 86400


def migrate(conn):
    if conn.execute("SELECT 1 FROM schema_migrations WHERE version=4").fetchone():
        return
    conn.execute(
        "ALTER TABLE reminders ADD COLUMN repeat_rule TEXT CHECK(repeat_rule IS NULL OR repeat_rule='weekly')"
    )
    conn.execute(
        "CREATE TABLE reminder_occurrences (event_id TEXT PRIMARY KEY, reminder_id INTEGER NOT NULL REFERENCES reminders(id) ON DELETE CASCADE, remind_at TEXT NOT NULL, status TEXT NOT NULL, attempts INTEGER NOT NULL, finished_at REAL NOT NULL)"
    )
    conn.execute(
        "CREATE TABLE weather_tip_cache (city TEXT NOT NULL, target_date TEXT NOT NULL, payload TEXT NOT NULL, PRIMARY KEY(city,target_date))"
    )
    conn.execute(
        "CREATE TABLE weather_tips (city TEXT NOT NULL, target_date TEXT NOT NULL, tip TEXT NOT NULL, PRIMARY KEY(city,target_date))"
    )
    conn.execute(
        "INSERT INTO schema_migrations VALUES (4,?)", (config.REMINDER_NAIVE_OFFSET_MINUTES,)
    )


def advance(conn, reminder_id, now, *, missed=False):
    from .reminder_store import seed_delivery

    row = conn.execute(
        "SELECT r.*, d.event_id,d.status,d.attempts,d.due_at FROM reminders r JOIN reminder_deliveries d ON d.reminder_id=r.id WHERE r.id=? AND r.repeat_rule='weekly' AND r.done=0",
        (reminder_id,),
    ).fetchone()
    if row is None:
        return
    phone = conn.execute(
        "SELECT status,attempts FROM wechat_subscriptions WHERE reminder_id=? AND event_id=?",
        (reminder_id, row["event_id"]),
    ).fetchone()
    if not missed:
        if row["channel"] in ("pc", "both") and row["status"] not in ("sent", "failed"):
            return
        if row["channel"] in ("phone", "both"):
            if phone is not None and phone[0] in ("pending", "retry", "sending"):
                return
            if row["channel"] == "phone" and phone is None:
                return
    due = row["due_at"]
    if due is None:
        return
    steps = max(1, int((now - due) // WEEK) + 1)
    next_due = datetime.fromisoformat(row["remind_at"]) + timedelta(weeks=steps)
    conn.execute(
        "INSERT OR IGNORE INTO reminder_occurrences VALUES (?,?,?,?,?,?)",
        (
            row["event_id"],
            reminder_id,
            row["remind_at"],
            "skipped"
            if missed
            else (phone[0] if row["channel"] == "phone" and phone else row["status"]),
            phone[1] if row["channel"] == "phone" and phone else row["attempts"],
            now,
        ),
    )
    conn.execute(
        "UPDATE wechat_subscriptions SET status='cancelled',last_error='cycle_advanced' WHERE reminder_id=? AND event_id=? AND status IN ('pending','retry','sending')",
        (reminder_id, row["event_id"]),
    )
    conn.execute("UPDATE reminders SET remind_at=? WHERE id=?", (next_due.isoformat(), reminder_id))
    conn.execute("DELETE FROM reminder_deliveries WHERE reminder_id=?", (reminder_id,))
    updated = dict(conn.execute("SELECT * FROM reminders WHERE id=?", (reminder_id,)).fetchone())
    seed_delivery(conn, updated)


def maintain(now):
    """跨过整周的旧事件直接跳到未来；不累积离线补发。"""
    with db._conn() as conn:
        conn.execute("BEGIN IMMEDIATE")
        maintain_in(conn, now)


def maintain_in(conn, now):
    """与领取共用事务，避免额外的锁等待改变原调度器语义。"""
    rows = conn.execute(
        "SELECT r.id,d.due_at FROM reminders r JOIN reminder_deliveries d ON d.reminder_id=r.id WHERE r.repeat_rule='weekly' AND r.done=0 AND d.due_at<=?",
        (now,),
    ).fetchall()
    for row in rows:
        advance(conn, row["id"], now, missed=now - row["due_at"] >= WEEK)
