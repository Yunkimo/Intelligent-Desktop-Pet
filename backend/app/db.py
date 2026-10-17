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
    from .reminder_store import migrate
    from .wechat_store import migrate as migrate_wechat

    with _conn() as conn:
        conn.executescript(_SCHEMA)
        migrate(conn)
        columns = {row[1] for row in conn.execute("PRAGMA table_info(courses)")}
        if "teacher" not in columns:
            conn.execute("ALTER TABLE courses ADD COLUMN teacher TEXT NOT NULL DEFAULT ''")
        migrate_wechat(conn)


def _get_by_id(table: str, row_id: int) -> dict | None:
    with _conn() as conn:
        row = conn.execute(f"SELECT * FROM {table} WHERE id = ?", (row_id,)).fetchone()
    return dict(row) if row else None


def _delete(table: str, row_id: int) -> bool:
    with _conn() as conn:
        cur = conn.execute(f"DELETE FROM {table} WHERE id = ?", (row_id,))
    return cur.rowcount > 0


def _apply_update(table: str, columns: set[str], row_id: int, fields: dict) -> dict | None:
    """按白名单列更新；weeks 转 JSON、done 转 0/1。table/columns 仅由本模块传入。"""
    updates = {k: v for k, v in fields.items() if k in columns}
    if "weeks" in updates:
        updates["weeks"] = json.dumps(updates["weeks"] or [], ensure_ascii=False)
    if "done" in updates:
        updates["done"] = int(bool(updates["done"]))
    if updates:
        set_sql = ", ".join(f"{k} = ?" for k in updates)
        with _conn() as conn:
            conn.execute(f"UPDATE {table} SET {set_sql} WHERE id = ?", (*updates.values(), row_id))
    return _get_by_id(table, row_id)


# ---------- 课表 courses ----------


def list_courses() -> list[dict]:
    with _conn() as conn:
        rows = conn.execute("SELECT * FROM courses ORDER BY day_of_week, start_time").fetchall()
    return [dict(r) for r in rows]


def create_course(
    name, day_of_week, start_time, end_time, location="", teacher="", weeks=None
) -> dict:
    with _conn() as conn:
        cur = conn.execute(
            "INSERT INTO courses (name, day_of_week, start_time, end_time, location, teacher, weeks) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                name,
                day_of_week,
                start_time,
                end_time,
                location,
                teacher,
                json.dumps(weeks or [], ensure_ascii=False),
            ),
        )
        new_id = cur.lastrowid
    return _get_by_id("courses", new_id)


def create_courses_bulk(courses: list[dict]) -> list[dict]:
    """单事务批量插入课表；任一失败整体回滚（courses 已通过 CourseIn 校验）。"""
    if not courses:
        return []
    with _conn() as conn:
        ids: list[int] = []
        for course in courses:
            cur = conn.execute(
                "INSERT INTO courses (name, day_of_week, start_time, end_time, location, teacher, weeks) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    course["name"],
                    course["day_of_week"],
                    course["start_time"],
                    course["end_time"],
                    course.get("location", ""),
                    course.get("teacher", ""),
                    json.dumps(course.get("weeks") or [], ensure_ascii=False),
                ),
            )
            ids.append(cur.lastrowid)
        placeholders = ", ".join("?" for _ in ids)
        rows = conn.execute(
            f"SELECT * FROM courses WHERE id IN ({placeholders}) ORDER BY id", ids
        ).fetchall()
    return [dict(r) for r in rows]


def update_course(course_id: int, fields: dict) -> dict | None:
    cols = {"name", "day_of_week", "start_time", "end_time", "location", "teacher", "weeks"}
    return _apply_update("courses", cols, course_id, fields)


def delete_course(course_id: int) -> bool:
    return _delete("courses", course_id)


# ---------- 日程/待办 tasks ----------


def list_tasks() -> list[dict]:
    with _conn() as conn:
        rows = conn.execute("SELECT * FROM tasks ORDER BY done, due_at, created_at").fetchall()
    return [dict(r) for r in rows]


def create_task(title, note="", due_at=None, remind_at=None) -> dict:
    with _conn() as conn:
        cur = conn.execute(
            "INSERT INTO tasks (title, note, due_at, remind_at, created_at) VALUES (?, ?, ?, ?, ?)",
            (title, note, due_at, remind_at, _iso_now()),
        )
        new_id = cur.lastrowid
    return _get_by_id("tasks", new_id)


def update_task(task_id: int, fields: dict) -> dict | None:
    cols = {"title", "note", "due_at", "remind_at", "done"}
    return _apply_update("tasks", cols, task_id, fields)


def delete_task(task_id: int) -> bool:
    return _delete("tasks", task_id)


# ---------- 提醒 reminders ----------


def list_reminders() -> list[dict]:
    with _conn() as conn:
        rows = conn.execute("SELECT * FROM reminders ORDER BY done, remind_at").fetchall()
    return [dict(r) for r in rows]


def create_reminder(
    title, remind_at, body="", channel="both", task_id=None, wechat_user_id=None
) -> dict:
    """创建提醒及持久化调度状态，两者在同一事务提交。"""
    from .reminder_store import seed_delivery
    from .reminder_time import normalize_reminder_time

    remind_at = normalize_reminder_time(remind_at)
    with _conn() as conn:
        cur = conn.execute(
            "INSERT INTO reminders (title, body, remind_at, channel, task_id, wechat_user_id) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (title, body, remind_at, channel, task_id, wechat_user_id),
        )
        new_id = cur.lastrowid
        seed_delivery(
            conn, dict(conn.execute("SELECT * FROM reminders WHERE id=?", (new_id,)).fetchone())
        )
    return _get_by_id("reminders", new_id)


def update_reminder(reminder_id: int, fields: dict) -> dict | None:
    """编辑时失效旧领取；重新安排时间或显式 done=false 开始新逻辑事件。"""
    from .reminder_store import seed_delivery
    from .reminder_time import normalize_reminder_time

    cols = {"title", "body", "remind_at", "channel", "done", "task_id", "wechat_user_id"}
    updates = {key: value for key, value in fields.items() if key in cols}
    if not updates:
        return _get_by_id("reminders", reminder_id)
    if "remind_at" in updates:
        updates["remind_at"] = normalize_reminder_time(updates["remind_at"])
    if {"remind_at", "channel"} & updates.keys():
        updates.setdefault("done", False)
    if "done" in updates:
        updates["done"] = int(updates["done"])
    with _conn() as conn:
        conn.execute("BEGIN IMMEDIATE")
        set_sql = ", ".join(f"{key}=?" for key in updates)
        conn.execute(f"UPDATE reminders SET {set_sql} WHERE id=?", (*updates.values(), reminder_id))
        row = conn.execute("SELECT * FROM reminders WHERE id=?", (reminder_id,)).fetchone()
        if row is None:
            return None
        conn.execute("DELETE FROM reminder_deliveries WHERE reminder_id=?", (reminder_id,))
        seed_delivery(conn, dict(row))
    return _get_by_id("reminders", reminder_id)


def delete_reminder(reminder_id: int) -> bool:
    return _delete("reminders", reminder_id)
