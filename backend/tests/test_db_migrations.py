"""课表教师字段与提醒调度迁移共同升级时的数据兼容性回归。"""

import asyncio
import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from app import config, db, reminder_store
from app.scheduler import Scheduler


@pytest.mark.parametrize("has_teacher", [False, True])
@pytest.mark.parametrize("has_scheduler", [False, True])
def test_course_and_reminder_migrations_coexist(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, has_teacher: bool, has_scheduler: bool
) -> None:
    """从任一分支的数据库升级后保留课程、提醒事件及调度能力。"""
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "upgrade.db")
    schema = db._SCHEMA
    if not has_teacher:
        schema = schema.replace("    teacher TEXT NOT NULL DEFAULT '',\n", "")
    with db._conn() as conn:
        conn.executescript(schema)
        conn.execute(
            "INSERT INTO courses(name,day_of_week,start_time,end_time,weeks) "
            "VALUES ('数学',1,'08:00','09:40','[1, 2]')"
        )
        if has_teacher:
            conn.execute("UPDATE courses SET teacher='王老师'")
        conn.execute(
            "INSERT INTO reminders(title,remind_at) VALUES ('复习','2040-01-01T08:00:00+08:00')"
        )
        conn.commit()
        if has_scheduler:
            reminder_store.migrate(conn)
    previous_event = reminder_store.delivery_status(1)["event_id"] if has_scheduler else None

    db.init_db()
    event_id = reminder_store.delivery_status(1)["event_id"]
    db.init_db()

    course = db.list_courses()[0]
    assert course["name"] == "数学"
    assert course["weeks"] == "[1, 2]"
    assert course["teacher"] == ("王老师" if has_teacher else "")
    assert reminder_store.delivery_status(1)["event_id"] == event_id
    if previous_event is not None:
        assert event_id == previous_event
    if not has_scheduler:
        backups = list(tmp_path.glob("upgrade.pre-b2-*.db"))
        assert len(backups) == 1
        with closing(sqlite3.connect(backups[0])) as backup:
            columns = {row[1] for row in backup.execute("PRAGMA table_info(courses)")}
            assert ("teacher" in columns) == has_teacher

    created = db.create_courses_bulk(
        [
            {
                "name": "英语",
                "day_of_week": 2,
                "start_time": "10:00",
                "end_time": "11:40",
                "teacher": "李老师",
            }
        ]
    )
    assert created[0]["teacher"] == "李老师"
    broadcast = AsyncMock(return_value=1)
    now = datetime(2040, 1, 1, tzinfo=timezone.utc).timestamp()
    assert asyncio.run(Scheduler(broadcast, lambda: now).run_once()) == 1
    assert broadcast.await_count == 1
    assert reminder_store.delivery_status(1)["status"] == "sent"
    assert db.list_reminders()[0]["done"] == 1
