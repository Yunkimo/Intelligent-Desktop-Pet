"""SQLite 数据访问层：建表 + 轻量 CRUD（标准库 sqlite3，无 ORM）。

沿用项目轻量风格：记录用 dict 承载；布尔/列表字段在边界处显式转换。
"""

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime

from . import config


def _iso_now() -> str:
    return datetime.now().isoformat(timespec="seconds")


_SCHEMA = """
CREATE TABLE IF NOT EXISTS semester_settings (
    scope TEXT PRIMARY KEY,
    start_date TEXT NOT NULL,
    total_weeks INTEGER NOT NULL CHECK(total_weeks BETWEEN 1 AND 53),
    timezone TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS courses (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    day_of_week INTEGER NOT NULL,
    start_time TEXT NOT NULL,
    end_time TEXT NOT NULL,
    location TEXT NOT NULL DEFAULT '',
    teacher TEXT NOT NULL DEFAULT '',
    weeks TEXT NOT NULL DEFAULT '[]'
);
CREATE TABLE IF NOT EXISTS tasks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    note TEXT NOT NULL DEFAULT '',
    due_at TEXT,
    remind_at TEXT,
    done INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS reminders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    body TEXT NOT NULL DEFAULT '',
    remind_at TEXT NOT NULL,
    channel TEXT NOT NULL DEFAULT 'both',
    done INTEGER NOT NULL DEFAULT 0,
    task_id INTEGER
);
"""


@contextmanager
def _conn():
    config.DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(config.DB_PATH), timeout=config.DB_TIMEOUT_SECONDS)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db() -> None:
    """幂等建表，保留提醒迁移及其备份，再补充课表教师字段。"""
    from . import accounts

    accounts.backup_before_upgrade()
    from .reminder_store import migrate
    from .wechat_store import migrate as migrate_wechat

    with _conn() as conn:
        conn.executescript(_SCHEMA)
        migrate(conn)
        columns = {row[1] for row in conn.execute("PRAGMA table_info(courses)")}
        if "teacher" not in columns:
            conn.execute("ALTER TABLE courses ADD COLUMN teacher TEXT NOT NULL DEFAULT ''")
        migrate_wechat(conn)
    # SQLite 给非空旧表增加带默认值的外键列时需暂停外键检查；升级事务完成前全库复核。
    with _conn() as conn:
        conn.execute("PRAGMA foreign_keys=OFF")
        conn.execute("BEGIN IMMEDIATE")
        accounts.migrate(conn)
        if conn.execute("PRAGMA foreign_key_check").fetchone():
            raise RuntimeError("B8 migration foreign key check failed")

    accounts.backup_before_upgrade(version=4, label="b5-repeat")
    from . import recurrence

    with _conn() as conn:
        conn.execute("BEGIN IMMEDIATE")
        recurrence.migrate(conn)

    accounts.backup_before_upgrade(version=5, label="weather-subscriptions")
    from . import weather_subscriptions

    with _conn() as conn:
        conn.execute("BEGIN IMMEDIATE")
        weather_subscriptions.migrate(conn)


def _get_by_id(table: str, row_id: int, user_id: int = 1) -> dict | None:
    with _conn() as conn:
        row = conn.execute(
            f"SELECT * FROM {table} WHERE id = ? AND user_id=?", (row_id, user_id)
        ).fetchone()
    return dict(row) if row else None


def _delete(table: str, row_id: int, user_id: int = 1) -> bool:
    with _conn() as conn:
        cur = conn.execute(f"DELETE FROM {table} WHERE id = ? AND user_id=?", (row_id, user_id))
    return cur.rowcount > 0


def _apply_update(
    table: str, columns: set[str], row_id: int, fields: dict, user_id: int = 1
) -> dict | None:
    """按白名单列更新；weeks 转 JSON、done 转 0/1。table/columns 仅由本模块传入。"""
    updates = {k: v for k, v in fields.items() if k in columns}
    if "weeks" in updates:
        updates["weeks"] = json.dumps(updates["weeks"] or [], ensure_ascii=False)
    if "done" in updates:
        updates["done"] = int(bool(updates["done"]))
    if updates:
        set_sql = ", ".join(f"{k} = ?" for k in updates)
        with _conn() as conn:
            conn.execute(
                f"UPDATE {table} SET {set_sql} WHERE id = ? AND user_id=?",
                (*updates.values(), row_id, user_id),
            )
    return _get_by_id(table, row_id, user_id)


# ---------- 课表 courses ----------


def list_courses(user_id: int = 1) -> list[dict]:
    with _conn() as conn:
        rows = conn.execute(
            "SELECT * FROM courses WHERE user_id=? ORDER BY day_of_week, start_time", (user_id,)
        ).fetchall()
    return [dict(r) for r in rows]


def create_course(
    name, day_of_week, start_time, end_time, location="", teacher="", weeks=None, user_id: int = 1
) -> dict:
    with _conn() as conn:
        cur = conn.execute(
            "INSERT INTO courses (name, day_of_week, start_time, end_time, location, teacher, weeks, user_id) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                name,
                day_of_week,
                start_time,
                end_time,
                location,
                teacher,
                json.dumps(weeks or [], ensure_ascii=False),
                user_id,
            ),
        )
        new_id = cur.lastrowid
    return _get_by_id("courses", new_id, user_id)


def create_courses_bulk(courses: list[dict], user_id: int = 1) -> list[dict]:
    """单事务批量插入课表；任一失败整体回滚（courses 已通过 CourseIn 校验）。"""
    if not courses:
        return []
    with _conn() as conn:
        ids: list[int] = []
        for course in courses:
            cur = conn.execute(
                "INSERT INTO courses (name, day_of_week, start_time, end_time, location, teacher, weeks, user_id) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    course["name"],
                    course["day_of_week"],
                    course["start_time"],
                    course["end_time"],
                    course.get("location", ""),
                    course.get("teacher", ""),
                    json.dumps(course.get("weeks") or [], ensure_ascii=False),
                    user_id,
                ),
            )
            ids.append(cur.lastrowid)
        placeholders = ", ".join("?" for _ in ids)
        rows = conn.execute(
            f"SELECT * FROM courses WHERE id IN ({placeholders}) ORDER BY id", ids
        ).fetchall()
    return [dict(r) for r in rows]


def update_course(course_id: int, fields: dict, user_id: int = 1) -> dict | None:
    cols = {"name", "day_of_week", "start_time", "end_time", "location", "teacher", "weeks"}
    return _apply_update("courses", cols, course_id, fields, user_id)


def delete_course(course_id: int, user_id: int = 1) -> bool:
    return _delete("courses", course_id, user_id)


# ---------- 日程/待办 tasks ----------


def list_tasks(user_id: int = 1) -> list[dict]:
    with _conn() as conn:
        rows = conn.execute(
            "SELECT * FROM tasks WHERE user_id=? ORDER BY done, due_at, created_at", (user_id,)
        ).fetchall()
    return [dict(r) for r in rows]


def create_task(
    title: str,
    note: str = "",
    due_at: str | None = None,
    remind_at: str | None = None,
    user_id: int = 1,
) -> dict:
    """日程和默认桌面提醒原子创建，写入失败时一起回滚。"""
    from .reminder_time import normalize_reminder_time

    if remind_at is not None:
        normalize_reminder_time(remind_at)
    with _conn() as conn:
        conn.execute("BEGIN IMMEDIATE")
        cur = conn.execute(
            "INSERT INTO tasks (title, note, due_at, remind_at, created_at, user_id) VALUES (?, ?, ?, ?, ?, ?)",
            (title, note, due_at, remind_at, _iso_now(), user_id),
        )
        new_id = cur.lastrowid
        task = dict(conn.execute("SELECT * FROM tasks WHERE id=?", (new_id,)).fetchone())
        _sync_task_reminders(conn, task, reopened=False)
        return task


def update_task(task_id: int, fields: dict, user_id: int = 1) -> dict | None:
    """日程改期与关联提醒在同一事务更新，取消旧事件的待发授权。"""
    from .reminder_time import normalize_reminder_time

    cols = {"title", "note", "due_at", "remind_at", "done"}
    updates = {key: value for key, value in fields.items() if key in cols}
    with _conn() as conn:
        conn.execute("BEGIN IMMEDIATE")
        old = conn.execute(
            "SELECT * FROM tasks WHERE id=? AND user_id=?", (task_id, user_id)
        ).fetchone()
        if old is None:
            return None
        if "remind_at" in updates and updates["remind_at"] is not None:
            updates["remind_at"] = normalize_reminder_time(updates["remind_at"])
        if updates:
            sql = ", ".join(f"{key}=?" for key in updates)
            conn.execute(f"UPDATE tasks SET {sql} WHERE id=?", (*updates.values(), task_id))
        task = dict(
            conn.execute(
                "SELECT * FROM tasks WHERE id=? AND user_id=?", (task_id, user_id)
            ).fetchone()
        )
        if updates:
            _sync_task_reminders(conn, task, reopened=bool(old["done"] and not task["done"]))
        return task


def _sync_task_reminders(conn: sqlite3.Connection, task: dict, *, reopened: bool) -> None:
    """复用现有关联提醒；不为历史记录启动时补发，也不隐式申请微信授权。"""
    from .reminder_store import seed_delivery
    from .reminder_time import normalize_reminder_time

    rows = conn.execute(
        "SELECT * FROM reminders WHERE task_id=? ORDER BY id", (task["id"],)
    ).fetchall()
    if not task["remind_at"]:
        conn.execute("DELETE FROM reminders WHERE task_id=?", (task["id"],))
        return
    if task["done"]:
        for row in rows:
            pending_phone = conn.execute(
                "SELECT 1 FROM wechat_subscriptions WHERE reminder_id=? "
                "AND status IN ('pending','retry','sending') LIMIT 1",
                (row["id"],),
            ).fetchone()
            if not row["done"] or pending_phone:
                _update_reminder(conn, row["id"], {"done": True})
        return
    try:
        due = normalize_reminder_time(task["remind_at"])
    except ValueError:
        # 非法历史时间允许编辑其他字段；必须显式修复时间才能安排发送。
        return
    desktop = [r for r in rows if r["channel"] in ("pc", "both")]
    for row in rows:
        # 历史重复桌面关联只保留首条，微信专用记录按用户分别保留。
        if row["channel"] in ("pc", "both") and row["id"] != desktop[0]["id"]:
            conn.execute("DELETE FROM reminders WHERE id=?", (row["id"],))
            continue
        fields = {"remind_at": due}
        if not row["done"]:
            fields.update(title=task["title"], body=task["note"])
        if reopened:
            fields.update(done=False, title=task["title"], body=task["note"])
        elif row["remind_at"] != due:
            fields.update(title=task["title"], body=task["note"])
        _update_reminder(conn, row["id"], fields)
    if not desktop:
        rid = conn.execute(
            "INSERT INTO reminders(title,body,remind_at,channel,task_id,user_id) VALUES (?,?,?,'pc',?,?)",
            (task["title"], task["note"], due, task["id"], task["user_id"]),
        ).lastrowid
        seed_delivery(
            conn, dict(conn.execute("SELECT * FROM reminders WHERE id=?", (rid,)).fetchone())
        )


def delete_task(task_id: int, user_id: int = 1) -> bool:
    """删除关联提醒和授权，避免客户端清理失败后留下孤儿发送。"""
    with _conn() as conn:
        conn.execute("BEGIN IMMEDIATE")
        if (
            conn.execute(
                "SELECT 1 FROM tasks WHERE id=? AND user_id=?", (task_id, user_id)
            ).fetchone()
            is None
        ):
            return False
        conn.execute("DELETE FROM reminders WHERE task_id=? AND user_id=?", (task_id, user_id))
        return conn.execute("DELETE FROM tasks WHERE id=?", (task_id,)).rowcount > 0


# ---------- 提醒 reminders ----------


def list_reminders(user_id: int = 1) -> list[dict]:
    with _conn() as conn:
        rows = conn.execute(
            "SELECT * FROM reminders WHERE user_id=? ORDER BY done, remind_at", (user_id,)
        ).fetchall()
    return [dict(r) for r in rows]


def create_reminder(
    title,
    remind_at,
    body="",
    channel="both",
    task_id=None,
    wechat_user_id=None,
    user_id: int = 1,
    repeat_rule=None,
) -> dict:
    """创建提醒及持久化调度状态，两者在同一事务提交。"""
    from .reminder_store import seed_delivery
    from .reminder_time import normalize_reminder_time

    remind_at = normalize_reminder_time(remind_at)
    with _conn() as conn:
        conn.execute("BEGIN IMMEDIATE")
        _validate_repeat(repeat_rule, task_id)
        _validate_reminder_links(conn, task_id, wechat_user_id, user_id)
        if task_id is not None and channel in ("pc", "both"):
            task = conn.execute(
                "SELECT * FROM tasks WHERE id=? AND user_id=?", (task_id, user_id)
            ).fetchone()
            if task is None or task["done"] or not task["remind_at"]:
                raise ValueError("task_reminder_unavailable")
            if normalize_reminder_time(task["remind_at"]) != remind_at:
                raise ValueError("task_reminder_time_mismatch")
            existing = conn.execute(
                "SELECT * FROM reminders WHERE task_id=? AND channel IN ('pc','both') ORDER BY id",
                (task_id,),
            ).fetchone()
            if existing is not None:
                return dict(existing)
        cur = conn.execute(
            "INSERT INTO reminders (title, body, remind_at, channel, task_id, wechat_user_id, user_id, repeat_rule) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (title, body, remind_at, channel, task_id, wechat_user_id, user_id, repeat_rule),
        )
        new_id = cur.lastrowid
        seed_delivery(
            conn, dict(conn.execute("SELECT * FROM reminders WHERE id=?", (new_id,)).fetchone())
        )
    return _get_by_id("reminders", new_id, user_id)


def update_reminder(reminder_id: int, fields: dict, user_id: int = 1) -> dict | None:
    """编辑时失效旧领取；重新安排时间或显式 done=false 开始新逻辑事件。"""
    with _conn() as conn:
        conn.execute("BEGIN IMMEDIATE")
        old = conn.execute(
            "SELECT * FROM reminders WHERE id=? AND user_id=?", (reminder_id, user_id)
        ).fetchone()
        if old is None:
            return None
        _validate_reminder_links(
            conn,
            fields.get("task_id", old["task_id"]),
            fields.get("wechat_user_id", old["wechat_user_id"]),
            user_id,
        )
        _validate_repeat(
            fields.get("repeat_rule", old["repeat_rule"]), fields.get("task_id", old["task_id"])
        )
        return _update_reminder(conn, reminder_id, fields)


def _update_reminder(conn: sqlite3.Connection, reminder_id: int, fields: dict) -> dict | None:
    """共享事务中的提醒更新；等价时间及无变化写入不会生成新事件。"""
    from .reminder_store import seed_delivery
    from .reminder_time import normalize_reminder_time

    old = conn.execute("SELECT * FROM reminders WHERE id=?", (reminder_id,)).fetchone()
    if old is None:
        return None
    cols = {
        "title",
        "body",
        "remind_at",
        "channel",
        "done",
        "task_id",
        "wechat_user_id",
        "repeat_rule",
    }
    updates = {key: value for key, value in fields.items() if key in cols}
    if "remind_at" in updates:
        updates["remind_at"] = normalize_reminder_time(updates["remind_at"])
    updates = {key: value for key, value in updates.items() if value != old[key] or key == "done"}
    if not updates:
        return dict(old)
    if old["repeat_rule"] and "repeat_rule" in updates and updates["repeat_rule"] is None:
        updates["done"] = True
    if {"remind_at", "channel", "repeat_rule"} & updates.keys():
        updates.setdefault("done", False)
    if "done" in updates:
        updates["done"] = int(updates["done"])
    set_sql = ", ".join(f"{key}=?" for key in updates)
    conn.execute(f"UPDATE reminders SET {set_sql} WHERE id=?", (*updates.values(), reminder_id))
    row = conn.execute("SELECT * FROM reminders WHERE id=?", (reminder_id,)).fetchone()
    if updates:
        conn.execute(
            "UPDATE wechat_subscriptions SET status='cancelled',last_error='reminder_changed' "
            "WHERE reminder_id=? AND status IN ('pending','retry')",
            (reminder_id,),
        )
        conn.execute("DELETE FROM reminder_deliveries WHERE reminder_id=?", (reminder_id,))
        seed_delivery(conn, dict(row))
    return dict(row)


def ensure_phone_reminder(task_id: int, user_id: int) -> dict:
    """按最新日程和会话用户原子复用手机提醒，历史重复数据需人工处理。"""
    from .reminder_store import seed_delivery
    from .reminder_time import normalize_reminder_time

    with _conn() as conn:
        conn.execute("BEGIN IMMEDIATE")
        wx_user_id = user_id
        owner = conn.execute(
            "SELECT business_user_id FROM wechat_users WHERE id=?", (wx_user_id,)
        ).fetchone()
        if owner is None:
            raise OwnershipError()
        user_id = owner[0]
        task = conn.execute(
            "SELECT * FROM tasks WHERE id=? AND user_id=?", (task_id, user_id)
        ).fetchone()
        if task is None:
            raise OwnershipError("resource_not_found")
        if task["done"] or not task["remind_at"]:
            raise ValueError("task_reminder_unavailable")
        due = normalize_reminder_time(task["remind_at"])
        rows = conn.execute(
            "SELECT * FROM reminders WHERE task_id=? AND wechat_user_id=? AND channel='phone'",
            (task_id, wx_user_id),
        ).fetchall()
        if len(rows) > 1:
            raise ValueError("duplicate_task_reminders")
        if rows:
            reminder_id = rows[0]["id"]
            fields = {"remind_at": due}
            if not rows[0]["done"] or rows[0]["remind_at"] != due:
                fields.update(title=task["title"], body=task["note"])
            _update_reminder(conn, reminder_id, fields)
        else:
            reminder_id = conn.execute(
                "INSERT INTO reminders(title,body,remind_at,channel,task_id,wechat_user_id,user_id) "
                "VALUES (?,?,?,'phone',?,?,?)",
                (task["title"], task["note"], due, task_id, wx_user_id, user_id),
            ).lastrowid
            seed_delivery(
                conn,
                dict(conn.execute("SELECT * FROM reminders WHERE id=?", (reminder_id,)).fetchone()),
            )
        return dict(
            conn.execute(
                "SELECT r.*,d.event_id FROM reminders r JOIN reminder_deliveries d "
                "ON d.reminder_id=r.id WHERE r.id=?",
                (reminder_id,),
            ).fetchone()
        )


def delete_reminder(reminder_id: int, user_id: int = 1) -> bool:
    return _delete("reminders", reminder_id, user_id)


class OwnershipError(ValueError):
    """统一不存在与越权语义，避免通过关联字段探测他人资源。"""


def _validate_reminder_links(conn, task_id, wechat_user_id, user_id):
    if (
        task_id is not None
        and conn.execute(
            "SELECT 1 FROM tasks WHERE id=? AND user_id=?", (task_id, user_id)
        ).fetchone()
        is None
    ):
        raise OwnershipError("resource_not_found")
    if (
        wechat_user_id is not None
        and conn.execute(
            "SELECT 1 FROM wechat_users WHERE id=? AND business_user_id=?",
            (wechat_user_id, user_id),
        ).fetchone()
        is None
    ):
        raise OwnershipError("resource_not_found")


def _validate_repeat(rule, task_id):
    if rule not in (None, "weekly"):
        raise ValueError("invalid_repeat_rule")
    if rule is not None and task_id is not None:
        raise ValueError("repeating_reminder_must_be_independent")
