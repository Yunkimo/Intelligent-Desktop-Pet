"""微信身份、一次性授权与发送状态；所有写入使用参数化 SQLite 事务。"""

import hashlib
import secrets
import sqlite3
import time

from . import config, db


class SubscriptionError(Exception):
    """可安全返回客户端的订阅冲突。"""


def migrate(conn: sqlite3.Connection) -> None:
    """增量、幂等创建微信表；不改写 B2 的事件或历史数据。"""
    conn.execute(
        "CREATE TABLE IF NOT EXISTS wechat_users (id INTEGER PRIMARY KEY AUTOINCREMENT, "
        "openid TEXT NOT NULL, created_at REAL NOT NULL, appid TEXT NOT NULL, UNIQUE(appid,openid))"
    )
    conn.execute(
        "CREATE TABLE IF NOT EXISTS wechat_sessions (token_hash TEXT PRIMARY KEY, "
        "user_id INTEGER NOT NULL REFERENCES wechat_users(id) ON DELETE CASCADE, "
        "expires_at REAL NOT NULL)"
    )
    columns = {row[1] for row in conn.execute("PRAGMA table_info(reminders)")}
    if "wechat_user_id" not in columns:
        conn.execute(
            "ALTER TABLE reminders ADD COLUMN wechat_user_id INTEGER REFERENCES wechat_users(id)"
        )
    conn.execute(
        "CREATE TABLE IF NOT EXISTS wechat_subscriptions ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, request_id TEXT NOT NULL UNIQUE, "
        "user_id INTEGER NOT NULL REFERENCES wechat_users(id), "
        "reminder_id INTEGER NOT NULL REFERENCES reminders(id) ON DELETE CASCADE, "
        "event_id TEXT NOT NULL, template_id TEXT NOT NULL, choice TEXT NOT NULL, "
        "status TEXT NOT NULL, attempts INTEGER NOT NULL DEFAULT 0, "
        "next_attempt_at REAL NOT NULL DEFAULT 0, lease_until REAL NOT NULL DEFAULT 0, "
        "last_error TEXT, created_at REAL NOT NULL, UNIQUE(reminder_id,event_id))"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS wechat_pending ON wechat_subscriptions(status,next_attempt_at)"
    )
    conn.execute(
        "INSERT OR IGNORE INTO schema_migrations VALUES (2,?)",
        (config.REMINDER_NAIVE_OFFSET_MINUTES,),
    )


def new_session(openid: str, now: float | None = None) -> dict:
    """签发随机会话，仅持久化摘要；同一用户再次登录撤销旧会话。"""
    now = time.time() if now is None else now
    token = secrets.token_urlsafe(32)
    digest = hashlib.sha256(token.encode()).hexdigest()
    with db._conn() as conn:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute(
            "INSERT OR IGNORE INTO wechat_users(openid,created_at,appid) VALUES (?,?,?)",
            (openid, now, config.WX_APPID),
        )
        user_id = conn.execute(
            "SELECT id FROM wechat_users WHERE appid=? AND openid=?", (config.WX_APPID, openid)
        ).fetchone()[0]
        conn.execute("DELETE FROM wechat_sessions WHERE user_id=? OR expires_at<=?", (user_id, now))
        conn.execute(
            "INSERT INTO wechat_sessions VALUES (?,?,?)",
            (digest, user_id, now + config.WX_SESSION_TTL_SECONDS),
        )
    return {
        "user_id": user_id,
        "openid": openid,
        "session_token": token,
        "expires_in": config.WX_SESSION_TTL_SECONDS,
    }


def session_user(token: str, now: float | None = None) -> int | None:
    """验证会话有效期及 AppID 归属；openid 本身不作为凭证。"""
    if not token or len(token) > 256:
        return None
    now = time.time() if now is None else now
    digest = hashlib.sha256(token.encode()).hexdigest()
    with db._conn() as conn:
        row = conn.execute(
            "SELECT s.user_id FROM wechat_sessions s JOIN wechat_users u ON u.id=s.user_id "
            "WHERE s.token_hash=? AND s.expires_at>? AND u.appid=?",
            (digest, now, config.WX_APPID),
        ).fetchone()
    return row[0] if row else None


def _public(row: sqlite3.Row | dict) -> dict:
    return {
        key: row[key]
        for key in (
            "request_id",
            "reminder_id",
            "event_id",
            "choice",
            "status",
            "attempts",
            "last_error",
        )
    }


def subscribe(
    user_id: int,
    reminder_id: int,
    request_id: str,
    template_id: str,
    choice: str,
    event_id: str | None = None,
) -> dict:
    """每个逻辑提醒只登记一条发送意图；客户端重放不会增加发送次数。"""
    with db._conn() as conn:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute(
            "SELECT r.*,d.event_id FROM reminders r JOIN reminder_deliveries d ON d.reminder_id=r.id "
            "WHERE r.id=? AND r.wechat_user_id=?",
            (reminder_id, user_id),
        ).fetchone()
        if row is None:
            raise SubscriptionError("reminder_not_found")
        if event_id is not None and event_id != row["event_id"]:
            raise SubscriptionError("reminder_event_changed")
        if row["channel"] not in {"phone", "both"}:
            raise SubscriptionError("reminder_has_no_phone_channel")
        existing = conn.execute(
            "SELECT * FROM wechat_subscriptions WHERE request_id=?", (request_id,)
        ).fetchone()
        if existing:
            if (
                existing["user_id"],
                existing["reminder_id"],
                existing["event_id"],
                existing["template_id"],
                existing["choice"],
            ) != (user_id, reminder_id, row["event_id"], template_id, choice):
                raise SubscriptionError("idempotency_conflict")
            return _public(existing)
        existing = conn.execute(
            "SELECT * FROM wechat_subscriptions WHERE reminder_id=? AND event_id=?",
            (reminder_id, row["event_id"]),
        ).fetchone()
        if existing:
            if existing["status"] == "rejected" and choice == "accept" and not row["done"]:
                conn.execute(
                    "UPDATE wechat_subscriptions SET request_id=?,choice='accept',status='pending',"
                    "template_id=?,created_at=? WHERE id=?",
                    (request_id, template_id, time.time(), existing["id"]),
                )
                return _public(
                    conn.execute(
                        "SELECT * FROM wechat_subscriptions WHERE id=?", (existing["id"],)
                    ).fetchone()
                )
            raise SubscriptionError("reminder_already_registered")
        if row["done"]:
            raise SubscriptionError("reminder_already_done")
        conn.execute(
            "INSERT INTO wechat_subscriptions(request_id,user_id,reminder_id,event_id,template_id,"
            "choice,status,created_at) VALUES (?,?,?,?,?,?,?,?)",
            (
                request_id,
                user_id,
                reminder_id,
                row["event_id"],
                template_id,
                choice,
                "pending" if choice == "accept" else "rejected",
                time.time(),
            ),
        )
        return _public(
            conn.execute(
                "SELECT * FROM wechat_subscriptions WHERE request_id=?", (request_id,)
            ).fetchone()
        )


def status(reminder_id: int, user_id: int | None = None) -> list[dict]:
    """返回脱敏历史，用户会话只能查询本人仍拥有的提醒。"""
    with db._conn() as conn:
        rows = conn.execute(
            "SELECT s.* FROM wechat_subscriptions s JOIN reminders r ON r.id=s.reminder_id "
            "WHERE s.reminder_id=? AND (? IS NULL OR (s.user_id=? AND r.wechat_user_id=?)) ORDER BY s.id",
            (reminder_id, user_id, user_id, user_id),
        ).fetchall()
    return [_public(row) for row in rows]


def claim_due(now: float) -> dict | None:
    """原子领取微信发送；租约过期标记不确定，不自动重复消费一次性订阅。"""
    with db._conn() as conn:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute(
            "UPDATE wechat_subscriptions SET status='uncertain',last_error='interrupted_send' "
            "WHERE status='sending' AND lease_until<=?",
            (now,),
        )
        conn.execute(
            "UPDATE wechat_subscriptions SET status='cancelled',last_error='reminder_changed' "
            "WHERE status IN ('pending','retry') AND NOT EXISTS ("
            "SELECT 1 FROM reminder_deliveries d JOIN reminders r ON r.id=d.reminder_id "
            "WHERE r.id=wechat_subscriptions.reminder_id AND d.event_id=wechat_subscriptions.event_id "
            "AND r.wechat_user_id=wechat_subscriptions.user_id AND r.channel IN ('phone','both') "
            "AND d.status!='cancelled')"
        )
        row = conn.execute(
            "SELECT s.*,u.openid,r.title,r.body,r.remind_at,r.task_id FROM wechat_subscriptions s "
            "JOIN reminders r ON r.id=s.reminder_id JOIN wechat_users u ON u.id=s.user_id "
            "JOIN reminder_deliveries d ON d.reminder_id=r.id AND d.event_id=s.event_id "
            "WHERE s.status IN ('pending','retry') AND s.next_attempt_at<=? AND d.due_at<=? "
            "AND u.appid=? ORDER BY d.due_at,s.id LIMIT 1",
            (now, now, config.WX_APPID),
        ).fetchone()
        if row is None:
            return None
        claim = dict(row)
        claim["attempts"] += 1
        conn.execute(
            "UPDATE wechat_subscriptions SET status='sending',attempts=?,lease_until=? WHERE id=?",
            (claim["attempts"], now + config.WX_DELIVERY_LEASE_SECONDS, claim["id"]),
        )
        return claim


def is_current(claim: dict) -> bool:
    """发送前复核授权、事件和收件人，减少编辑/删除后的过期通知。"""
    with db._conn() as conn:
        return (
            conn.execute(
                "SELECT 1 FROM wechat_subscriptions s JOIN reminders r ON r.id=s.reminder_id "
                "JOIN reminder_deliveries d ON d.reminder_id=r.id AND d.event_id=s.event_id "
                "WHERE s.id=? AND s.status='sending' AND s.attempts=? AND r.wechat_user_id=s.user_id "
                "AND d.status!='cancelled' AND r.channel IN ('phone','both')",
                (claim["id"], claim["attempts"]),
            ).fetchone()
            is not None
        )


def finish(claim: dict, now: float, outcome: str, error: str | None) -> None:
    """记录渠道结果；phone 成功完成提醒，both 仍保留桌面重试语义。"""
    with db._conn() as conn:
        conn.execute("BEGIN IMMEDIATE")
        changed = conn.execute(
            "UPDATE wechat_subscriptions SET status=?,last_error=?,next_attempt_at=?,lease_until=0 "
            "WHERE id=? AND status='sending' AND attempts=?",
            (
                outcome,
                error,
                now
                + min(
                    config.SCHEDULER_RETRY_SECONDS * 2 ** (claim["attempts"] - 1),
                    config.SCHEDULER_MAX_RETRY_SECONDS,
                ),
                claim["id"],
                claim["attempts"],
            ),
        ).rowcount
        if changed and outcome == "sent":
            conn.execute(
                "UPDATE reminders SET done=1 WHERE id=? AND channel='phone' AND wechat_user_id=? "
                "AND EXISTS(SELECT 1 FROM reminder_deliveries WHERE reminder_id=? AND event_id=?)",
                (claim["reminder_id"], claim["user_id"], claim["reminder_id"], claim["event_id"]),
            )
