"""按微信用户、城市和目标日期绑定的一次性天气订阅。"""

import json
import sqlite3
import time
from datetime import datetime, timedelta
from datetime import time as day_time
from uuid import uuid4
from zoneinfo import ZoneInfo

from . import config, db

ZONE = ZoneInfo("Asia/Shanghai")
PUBLIC = (
    "event_id",
    "city",
    "target_date",
    "send_at",
    "expires_at",
    "template_id",
    "choice",
    "status",
    "attempts",
    "weather_attempts",
    "last_error",
    "sent_at",
    "created_at",
)


class WeatherSubscriptionError(Exception):
    """对外返回稳定错误码。"""


def migrate(conn: sqlite3.Connection) -> None:
    conn.execute(
        "CREATE TABLE IF NOT EXISTS weather_subscriptions ("
        "event_id TEXT PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES wechat_users(id), "
        "city TEXT NOT NULL, city_key TEXT NOT NULL, target_date TEXT NOT NULL, "
        "send_at REAL NOT NULL, expires_at REAL NOT NULL, template_id TEXT NOT NULL, "
        "choice TEXT, status TEXT NOT NULL, attempts INTEGER NOT NULL DEFAULT 0, "
        "weather_attempts INTEGER NOT NULL DEFAULT 0, next_attempt_at REAL NOT NULL DEFAULT 0, "
        "lease_until REAL NOT NULL DEFAULT 0, last_error TEXT, forecast TEXT, sent_at REAL, "
        "created_at REAL NOT NULL, UNIQUE(user_id,city_key,target_date))"
    )
    conn.execute(
        "CREATE TABLE IF NOT EXISTS weather_subscription_requests ("
        "request_id TEXT PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES wechat_users(id), "
        "event_id TEXT NOT NULL REFERENCES weather_subscriptions(event_id), "
        "template_id TEXT NOT NULL, choice TEXT NOT NULL)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS weather_subscription_due "
        "ON weather_subscriptions(status,next_attempt_at,send_at)"
    )
    conn.execute(
        "INSERT OR IGNORE INTO schema_migrations VALUES (5,?)",
        (config.REMINDER_NAIVE_OFFSET_MINUTES,),
    )


def public(row: sqlite3.Row) -> dict:
    result = {key: row[key] for key in PUBLIC}
    result["forecast"] = json.loads(row["forecast"]) if row["forecast"] else None
    return result


def _owned(conn, event_id: str, user_id: int):
    row = conn.execute(
        "SELECT * FROM weather_subscriptions WHERE event_id=? AND user_id=?",
        (event_id, user_id),
    ).fetchone()
    if row is None:
        raise WeatherSubscriptionError("weather_event_not_found")
    return row


def prepare(user_id: int, city: str, now: float | None = None) -> dict:
    now = time.time() if now is None else now
    local = datetime.fromtimestamp(now, ZONE)
    today = local.date()
    target = (today + timedelta(days=1)).isoformat()
    send_at = datetime.combine(today, day_time(21), ZONE).timestamp()
    expires = datetime.combine(today + timedelta(days=1), day_time(), ZONE).timestamp()
    with db._conn() as conn:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute(
            "INSERT OR IGNORE INTO weather_subscriptions "
            "(event_id,user_id,city,city_key,target_date,send_at,expires_at,template_id,status,created_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?)",
            (
                str(uuid4()),
                user_id,
                city,
                city.casefold(),
                target,
                send_at,
                expires,
                config.WEATHER_WX_TEMPLATE_ID,
                "prepared",
                now,
            ),
        )
        row = conn.execute(
            "SELECT * FROM weather_subscriptions WHERE user_id=? AND city_key=? AND target_date=?",
            (user_id, city.casefold(), target),
        ).fetchone()
        return public(row)


def register(
    user_id: int,
    event_id: str,
    request_id: str,
    template_id: str,
    choice: str,
    now: float | None = None,
) -> dict:
    now = time.time() if now is None else now
    with db._conn() as conn:
        conn.execute("BEGIN IMMEDIATE")
        row = _owned(conn, event_id, user_id)
        existing = conn.execute(
            "SELECT * FROM weather_subscription_requests WHERE request_id=?", (request_id,)
        ).fetchone()
        if existing:
            if tuple(existing[k] for k in ("user_id", "event_id", "template_id", "choice")) != (
                user_id,
                event_id,
                template_id,
                choice,
            ):
                raise WeatherSubscriptionError("idempotency_conflict")
            return public(row)
        if row["expires_at"] <= now:
            raise WeatherSubscriptionError("weather_event_expired")
        if template_id != row["template_id"] or template_id != config.WEATHER_WX_TEMPLATE_ID:
            raise WeatherSubscriptionError("weather_template_changed")
        if row["status"] not in {"prepared", "rejected", "cancelled"}:
            raise WeatherSubscriptionError("weather_event_already_registered")
        conn.execute(
            "INSERT INTO weather_subscription_requests VALUES (?,?,?,?,?)",
            (request_id, user_id, event_id, template_id, choice),
        )
        conn.execute(
            "UPDATE weather_subscriptions SET choice=?,status=?,last_error=NULL,next_attempt_at=0 "
            "WHERE event_id=?",
            (choice, "pending" if choice == "accept" else "rejected", event_id),
        )
        return public(_owned(conn, event_id, user_id))


def detail(user_id: int, event_id: str) -> dict:
    with db._conn() as conn:
        return public(_owned(conn, event_id, user_id))


def list_owned(user_id: int) -> list[dict]:
    with db._conn() as conn:
        return [
            public(r)
            for r in conn.execute(
                "SELECT * FROM weather_subscriptions WHERE user_id=? ORDER BY created_at DESC LIMIT 100",
                (user_id,),
            )
        ]


def cancel(user_id: int, event_id: str) -> dict:
    with db._conn() as conn:
        conn.execute("BEGIN IMMEDIATE")
        row = _owned(conn, event_id, user_id)
        if row["status"] in {"sending", "uncertain", "sent"}:
            raise WeatherSubscriptionError("weather_send_already_started")
        conn.execute(
            "UPDATE weather_subscriptions SET status='cancelled',lease_until=0 WHERE event_id=?",
            (event_id,),
        )
        return public(_owned(conn, event_id, user_id))


def claim_due(now: float) -> dict | None:
    with db._conn() as conn:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute(
            "UPDATE weather_subscriptions SET status='uncertain',last_error='interrupted_send' "
            "WHERE status='sending' AND lease_until<=?",
            (now,),
        )
        conn.execute(
            "UPDATE weather_subscriptions SET status='pending',lease_until=0 "
            "WHERE status='checking' AND lease_until<=?",
            (now,),
        )
        conn.execute(
            "UPDATE weather_subscriptions SET status='expired',lease_until=0 "
            "WHERE expires_at<=? AND status IN ('prepared','pending','retry','retry_weather','checking')",
            (now,),
        )
        row = conn.execute(
            "SELECT s.*,u.openid FROM weather_subscriptions s JOIN wechat_users u ON u.id=s.user_id "
            "WHERE s.status IN ('pending','retry','retry_weather') AND s.send_at<=? "
            "AND s.expires_at>? AND s.next_attempt_at<=? AND u.appid=? "
            "ORDER BY s.send_at,s.created_at LIMIT 1",
            (now, now, now, config.WX_APPID),
        ).fetchone()
        if row is None:
            return None
        claim = dict(row)
        claim["weather_attempts"] += 1
        conn.execute(
            "UPDATE weather_subscriptions SET status='checking',weather_attempts=?,lease_until=? "
            "WHERE event_id=?",
            (
                claim["weather_attempts"],
                now + config.WX_DELIVERY_LEASE_SECONDS + config.WEB_QUERY_TIMEOUT_SECONDS,
                claim["event_id"],
            ),
        )
        return claim


def weather_result(claim: dict, forecast: dict, now: float) -> dict | None:
    """查询后事务复核取消/跨日，确认雨天才进入不可盲重试的发送阶段。"""
    with db._conn() as conn:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute(
            "SELECT * FROM weather_subscriptions WHERE event_id=? AND status='checking' "
            "AND weather_attempts=?",
            (claim["event_id"], claim["weather_attempts"]),
        ).fetchone()
        if row is None:
            return None
        status, error = "retry_weather", "weather_unavailable"
        if row["expires_at"] <= now:
            status, error = "expired", None
        elif row["template_id"] != config.WEATHER_WX_TEMPLATE_ID:
            status, error = "failed", "weather_template_changed"
        elif forecast.get("status") == "ok" and forecast.get("date") == row["target_date"]:
            if forecast.get("rain") is False:
                status, error = "no_rain", None
            elif forecast.get("rain") is True:
                status, error = "sending", None
        attempts = row["attempts"] + int(status == "sending")
        conn.execute(
            "UPDATE weather_subscriptions SET status=?,last_error=?,forecast=?,attempts=?,"
            "next_attempt_at=?,lease_until=? WHERE event_id=?",
            (
                status,
                error,
                json.dumps(forecast, ensure_ascii=False),
                attempts,
                now + 300,
                now + config.WX_DELIVERY_LEASE_SECONDS if status == "sending" else 0,
                row["event_id"],
            ),
        )
        return {**claim, "attempts": attempts} if status == "sending" else None


def finish(claim: dict, outcome: str, error: str | None, now: float) -> None:
    with db._conn() as conn:
        conn.execute(
            "UPDATE weather_subscriptions SET status=?,last_error=?,lease_until=0,"
            "next_attempt_at=?,sent_at=? WHERE event_id=? AND status='sending' AND attempts=?",
            (
                outcome,
                error,
                now
                + min(
                    config.SCHEDULER_RETRY_SECONDS * 2 ** (claim["attempts"] - 1),
                    config.SCHEDULER_MAX_RETRY_SECONDS,
                ),
                now if outcome == "sent" else None,
                claim["event_id"],
                claim["attempts"],
            ),
        )
