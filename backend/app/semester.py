"""学期设置与只读日历：按当地日期计算，不以秒数推算教学周。"""

import json
from datetime import date, datetime
from zoneinfo import ZoneInfo

from . import db

SHARED_SCOPE = "shared"


def _settings(conn, scope: str) -> dict | None:
    row = conn.execute(
        "SELECT start_date,total_weeks,timezone FROM semester_settings WHERE scope=?", (scope,)
    ).fetchone()
    return {"id": 1, **dict(row)} if row else None


def get_settings(scope: str = SHARED_SCOPE) -> dict:
    """作用域由服务端确定；当前路由仅开放共享演示作用域。"""
    with db._conn() as conn:
        settings = _settings(conn, scope)
    return {"configured": settings is not None, "settings": settings}


def save_settings(start_date: str, total_weeks: int, timezone: str, scope=SHARED_SCOPE) -> dict:
    """在同一事务写入并读回，返回前完成提交。"""
    with db._conn() as conn:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute(
            "INSERT INTO semester_settings(scope,start_date,total_weeks,timezone) VALUES (?,?,?,?) "
            "ON CONFLICT(scope) DO UPDATE SET start_date=excluded.start_date, "
            "total_weeks=excluded.total_weeks, timezone=excluded.timezone",
            (scope, start_date, total_weeks, timezone),
        )
        result = {"configured": True, "settings": _settings(conn, scope)}
    return result


def local_today(timezone: str) -> date:
    """获取配置时区的今天，供边界测试注入时钟。"""
    return datetime.now(ZoneInfo(timezone)).date()


def calendar(on_date: date | None = None, scope: str = SHARED_SCOPE) -> dict:
    """在一致读快照中读取配置和课程；不创建任何课程或提醒。"""
    with db._conn() as conn:
        conn.execute("BEGIN")
        settings = _settings(conn, scope)
        timezone = settings["timezone"] if settings else "Asia/Shanghai"
        day = on_date if on_date is not None else local_today(timezone)
        week = None
        status = "unconfigured"
        if settings:
            delta = (day - date.fromisoformat(settings["start_date"])).days
            if delta < 0:
                status = "before_term"
            elif delta >= settings["total_weeks"] * 7:
                status = "after_term"
            else:
                status, week = "in_term", delta // 7 + 1
        courses = []
        if week is not None:
            # B8 需同时给此课程查询加入认证用户过滤；不能仅隔离设置。
            rows = conn.execute(
                "SELECT * FROM courses WHERE day_of_week=? ORDER BY start_time,id",
                (day.isoweekday(),),
            ).fetchall()
            for row in rows:
                try:
                    weeks = json.loads(row["weeks"])
                except (TypeError, ValueError):
                    continue
                if isinstance(weeks, list) and all(type(w) is int and w > 0 for w in weeks):
                    if not weeks or week in weeks:
                        courses.append(dict(row))
    return {
        "date": day.isoformat(),
        "day_of_week": day.isoweekday(),
        "week": week,
        "status": status,
        "timezone": timezone,
        "settings": settings,
        "courses": courses,
    }
