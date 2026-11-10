"""一次性数字配对码及兑换尝试限制。事务由调用方管理。"""

import hashlib
import hmac
import math
import re
import secrets

from . import config

TTL_SECONDS = 90 * 24 * 60 * 60
SCHEMA_VERSION = 6
_CODE = re.compile(r"[0-9]{6}")
_SOURCE_LIMIT = (5, 15 * 60)
_GLOBAL_LIMIT = (20, 24 * 60 * 60)


class PairingUnavailable(Exception):
    """当前无法签发配对码。"""


class PairingRateLimited(Exception):
    def __init__(self, retry_after: int):
        self.retry_after = retry_after


def migrate(conn):
    if conn.execute(
        "SELECT 1 FROM schema_migrations WHERE version=?", (SCHEMA_VERSION,)
    ).fetchone():
        return
    conn.execute("ALTER TABLE device_pairings ADD COLUMN consumed_at REAL")
    conn.execute(
        "CREATE TABLE pairing_attempts (scope TEXT PRIMARY KEY, failures INTEGER NOT NULL, "
        "reset_at REAL NOT NULL)"
    )
    conn.execute(
        "INSERT INTO schema_migrations VALUES (?,?)",
        (SCHEMA_VERSION, config.REMINDER_NAIVE_OFFSET_MINUTES),
    )


def _code_hash(code: str) -> str:
    if not _CODE.fullmatch(code):
        # 兼容升级前尚未过期的长配对码。
        return hashlib.sha256(code.encode()).hexdigest()
    key = config.WX_SECRET or config.API_TOKEN
    if not key:
        raise PairingUnavailable
    return "v2:" + hmac.new(key.encode(), b"device-pairing:" + code.encode(), "sha256").hexdigest()


def issue(conn, user_id: int, now: float) -> str:
    conn.execute("DELETE FROM device_pairings WHERE expires_at<=?", (now,))
    for _ in range(32):
        code = f"{secrets.randbelow(1_000_000):06d}"
        code_hash = _code_hash(code)
        inserted = conn.execute(
            "INSERT INTO device_pairings(code_hash,user_id,expires_at) VALUES (?,?,?) "
            "ON CONFLICT(code_hash) DO NOTHING",
            (code_hash, user_id, now + TTL_SECONDS),
        )
        if inserted.rowcount:
            # 保留旧摘要至原到期时间，避免旧码被立刻重新分配给其他账号。
            conn.execute(
                "UPDATE device_pairings SET consumed_at=? "
                "WHERE user_id=? AND code_hash<>? AND consumed_at IS NULL",
                (now, user_id, code_hash),
            )
            return code
    raise PairingUnavailable


def consume(conn, code: str, now: float, source: str | None) -> int | None:
    scopes = [("global", *_GLOBAL_LIMIT)]
    if source is not None:
        source_hash = hashlib.sha256(source.encode()).hexdigest()
        scopes.append(("source:" + source_hash, *_SOURCE_LIMIT))
    retry_after = 0
    conn.execute("DELETE FROM pairing_attempts WHERE reset_at<=?", (now,))
    for scope, limit, _ in scopes:
        row = conn.execute(
            "SELECT failures,reset_at FROM pairing_attempts WHERE scope=?", (scope,)
        ).fetchone()
        if row and row["failures"] >= limit:
            retry_after = max(retry_after, math.ceil(row["reset_at"] - now))
    if retry_after:
        raise PairingRateLimited(retry_after)

    code_hash = _code_hash(code)
    row = conn.execute(
        "SELECT user_id FROM device_pairings WHERE code_hash=? AND expires_at>? "
        "AND consumed_at IS NULL",
        (code_hash, now),
    ).fetchone()
    if row is None:
        for scope, _, window in scopes:
            conn.execute(
                "INSERT INTO pairing_attempts VALUES (?,1,?) "
                "ON CONFLICT(scope) DO UPDATE SET failures=failures+1",
                (scope, now + window),
            )
        return None
    conn.execute("UPDATE device_pairings SET consumed_at=? WHERE code_hash=?", (now, code_hash))
    return row["user_id"]
