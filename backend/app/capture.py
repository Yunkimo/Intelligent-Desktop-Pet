"""Shared text capture for paired desktop and mini-program sessions."""

import json
import re
from datetime import datetime, time, timedelta, timezone
from hashlib import sha256
from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, field_validator
from starlette.concurrency import run_in_threadpool

from . import db
from .auth import current_session_user
from .task_parse import CLOCK, DAY, OFFSET, REMIND_NEG, hour_number, offset_delta, resolve_day

router = APIRouter(prefix="/api/capture", tags=["capture"])
BARE_TODO = re.compile(r"^(?:交|提交|买|取|寄|复习|缴费|还书|打电话)")
ACTION = re.compile(
    r"^(?:交|提交|写|读|看|买|取|寄|还|给|打电话|复习|整理|完成|准备|做|修|缴|付|拿|预约|联系)"
)
SCHEDULE = re.compile(r"开会|会议|面试|上课|讲座|考试|约见|预约|安排|预留|参加")
TODO = re.compile(r"^(?:请)?(?:帮我)?(?:记个?待办|添加待办|待办[:：]?)\s*")
EARLY = re.compile(r"提前(\d{1,3}|[一二两三四五六七八九十]+)(?:个)?(分钟|小时)(?:通知我|提醒我?)?")
QUESTION = re.compile(
    r"[？?]|^(?:查|查询|看看|告诉我|取消|删除|改期|修改|每周|每天)|几点|什么时候|怎么样|有没有|吗[。！!]?$"
)
DUE = re.compile(r"^(?:前|之前|以前|截止)|截止$")
DAY_TEXT = r"明早|今早|" + DAY.pattern
TIME = re.compile(r"(?:" + DAY_TEXT + r")?\s*" + CLOCK.pattern)
DATE = re.compile(DAY_TEXT)
RANGE = re.compile(r"^\s*(?:到|至|[-–—~～])\s*")
REMIND_WORD = re.compile(r"(?:请)?提醒我|通知我")
NO_REMINDER = re.compile(r"(?:不提醒|不用提醒|无需提醒|不要提醒)(?:我)?")
REMINDER_CHOICES = (
    (60, "提前 1 小时"),
    (30, "提前 30 分钟"),
    (10, "提前 10 分钟"),
    (None, "不提醒"),
)


class CaptureInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    text: str = Field(min_length=1, max_length=2000)
    timezone: str = "Asia/Shanghai"
    request_id: str = Field(min_length=1, max_length=128, pattern=r"^[a-zA-Z0-9_-]+$")

    @field_validator("timezone")
    @classmethod
    def valid_zone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError):
            raise ValueError("无效的时区") from None
        return value


class CaptureChoice(BaseModel):
    option: int = Field(ge=1)
    stage: Literal["item", "reminder"] = "item"


def _read_time(source: str, now: datetime, anchor=None):
    """Read a time at the start of a clause, keeping AM/PM ambiguity explicit."""
    relative = OFFSET.match(source)
    if relative and (delta := offset_delta(relative)) is not None:
        return [now + delta], None, relative.end()
    day_match = DATE.match(source)
    day = anchor
    day_word = day_match.group() if day_match else ""
    if day_match:
        if day_word in {"明早", "今早"}:
            day = now.date() + timedelta(days=int(day_word == "明早"))
        elif day_word.startswith("周"):
            weekday = "一二三四五六日".index(day_word[-1].replace("天", "日"))
            day = now.date() + timedelta(days=(weekday - now.weekday()) % 7)
        else:
            day = resolve_day(day_word, now.date())
    clock = TIME.match(source)
    if clock is None or day is None:
        return [], day, day_match.end() if day_match else 0
    period, hour, minutes, half, minute = clock.groups()
    h, m = hour_number(hour), int(minutes or minute or (30 if half else 0))
    if h >= 24 or m >= 60 or (period and not 1 <= h <= 12):
        raise ValueError("时间无效")
    if period in {"下午", "晚上"} or (period == "中午" and h < 6):
        hours = [h % 12 + 12]
    elif period in {"上午", "早上", "凌晨"} or day_word.endswith("早"):
        hours = [h % 12 if h == 12 else h]
    elif day_word.endswith("晚") and h <= 12:
        hours = [h % 12 + 12]
    elif period or minutes is not None or h == 0 or h > 12:
        hours = [h]
    else:
        hours = [h % 12, h % 12 + 12]
    return [datetime.combine(day, time(i, m), now.tzinfo) for i in hours], day, clock.end()


def _reply(message, status="needs_clarification", **fields):
    return {"status": status, "message": message, **fields}


def _plan(text: str, now: datetime) -> dict:
    remember = re.match(r"^(?:请)?(?:帮我)?(?:记一下|记下)", text)
    text = re.sub(r"^(?:请)?帮我", "", text).strip(" 。！!")
    if remember:
        text = re.sub(r"^(?:请)?(?:记一下|记下)", "待办", text, count=1)
    if not text or QUESTION.search(text):
        return _reply("可以输入一条待办、日程或提醒。", "not_action")
    explicit_todo = TODO.match(text)
    if explicit_todo:
        text = text[explicit_todo.end() :]
    main, *extra = re.split(r"[，,；;。\n]+", text)
    if not extra and (early_clause := EARLY.search(main)) and early_clause.start():
        main, extra = main[: early_clause.start()], [main[early_clause.start() :]]
    main = main.strip()
    skip_reminder = bool(extra and NO_REMINDER.fullmatch(extra[0].strip()))
    if REMIND_NEG.search(main) or (REMIND_NEG.search(text) and not skip_reminder):
        return _reply("请说明要创建的事项。已有提醒可以从列表取消。")
    standalone = bool(REMIND_WORD.search(main))
    if standalone and re.match(r"^(?:请)?(?:提醒|通知)我", main):
        main = REMIND_WORD.sub("", main, count=1)
    times, day, consumed = _read_time(main, now)
    title = main[consumed:].strip()
    due = bool(DUE.search(title))
    if due:
        title = DUE.sub("", title).strip()
    if standalone:
        title = REMIND_WORD.sub("", title, count=1).strip()
    schedule = bool(SCHEDULE.search(title)) and not due and not explicit_todo
    if not (
        due
        or explicit_todo
        or standalone
        or schedule
        or (consumed and ACTION.match(title))
        or BARE_TODO.match(title)
    ):
        return _reply("可以输入一条待办、日程或提醒。", "not_action")
    if not title or len(extra) > 1:
        return _reply("请每次说一件事，并写清事项名称和时间。")
    ends = []
    if times and (separator := RANGE.match(title)):
        ends, _, length = _read_time(title[separator.end() :], now, day)
        if not ends:
            return _reply("请补充日程的结束时间。")
        title = title[separator.end() + length :].strip()
        if not title:
            return _reply("请补充日程名称。")
        schedule = True
    if (schedule or standalone) and not times:
        return _reply("请补充具体时间，例如「明天上午九点」。")

    offset = None
    fixed = []
    if extra and not skip_reminder:
        clause = extra[0].strip()
        early = EARLY.fullmatch(clause) if times and not standalone else None
        if early:
            number = hour_number(early[1])
            if not 0 < number <= 180:
                return _reply("请给出有效的提前提醒时间。")
            offset = number * (60 if early[2] == "小时" else 1)
        elif REMIND_WORD.search(clause) or "提醒" in clause:
            fixed, _, _ = _read_time(clause, now, day)
            if not fixed:
                return _reply("请补充提醒时间。")
        else:
            return _reply("请分开录入多个事项。")

    kinds = (
        ["reminder"]
        if standalone
        else ["todo"]
        if due or explicit_todo
        else ["schedule"]
        if schedule
        else ["todo", "schedule"]
        if times and (offset is not None or skip_reminder)
        else ["todo", "reminder", "schedule"]
        if times
        else ["todo"]
    )
    options = []
    for kind in kinds:
        for instant in times or [None]:
            for end in ends or [None]:
                if end and end <= instant:
                    continue
                for reminder in fixed or [None]:
                    when = instant.isoformat() if instant else day.isoformat() if day else None
                    if kind == "reminder":
                        reminder = instant
                    elif offset is not None:
                        reminder = instant - timedelta(minutes=offset)
                    if (instant and instant < now) or (reminder and reminder < now):
                        continue
                    label = {"todo": "待办", "schedule": "日程", "reminder": "提醒"}[kind]
                    stamp = when[:16].replace("T", " ") if when else ""
                    action = {"todo": "截止", "schedule": "开始", "reminder": "通知"}[kind]
                    detail = f"{label}「{title}」" + (f" · {stamp} {action}" if stamp else "")
                    if end:
                        detail += f" · {end.isoformat()[11:16]} 结束"
                    if reminder and kind != "reminder":
                        detail += f" · {reminder.isoformat()[:16].replace('T', ' ')} 提醒"
                    options.append(
                        {
                            "label": detail,
                            "kind": kind,
                            "title": title,
                            "due_at": when if kind == "todo" else None,
                            "start_at": when if kind == "schedule" else None,
                            "end_at": end.isoformat() if end else None,
                            "remind_at": reminder.isoformat() if reminder else None,
                            "remind_before_minutes": offset,
                            "skip_reminder": skip_reminder,
                        }
                    )
    if not options or (not times and day and day < now.date()):
        return _reply("请确认时间，使用尚未过去的日期和时刻。")
    return {"options": options}


def _save(conn, owner, option):
    fields = {
        k: v
        for k, v in option.items()
        if k not in {"label", "kind", "skip_reminder", "choice_label", "disabled"}
    }
    kind = option["kind"]
    if kind == "reminder":
        item = db._insert_reminder(conn, owner, fields["title"], fields["remind_at"])
        event = "reminder.created"
    else:
        item = db._insert_task(conn, owner, kind=kind, **fields)
        event = "task.created"
    return _reply("已添加" + option["label"], "created", kind=kind, item=item), (event, item["id"])


def _finish_option(conn, owner, option, stage):
    now = datetime.now(timezone.utc)
    anchor_text = option["start_at"] or option["due_at"]
    anchor = datetime.fromisoformat(anchor_text) if anchor_text and "T" in anchor_text else None
    reminder = option["remind_at"]
    if (anchor and anchor <= now) or (reminder and datetime.fromisoformat(reminder) <= now):
        raise HTTPException(422, "提醒时间或事项时间已过，请选择其他选项或重新输入")
    if stage == "reminder" or not anchor or reminder or option.get("skip_reminder"):
        return _save(conn, owner, option)
    choices = []
    for minutes, label in REMINDER_CHOICES:
        instant = anchor - timedelta(minutes=minutes) if minutes is not None else None
        disabled = instant is not None and instant <= now
        choice_label = label + ("（默认）" if minutes == 60 else "")
        if disabled:
            choice_label += "（时间已过）"
        choices.append(
            {
                **option,
                "label": option["label"] + " · " + label + ("提醒" if instant else ""),
                "choice_label": choice_label,
                "disabled": disabled,
                "remind_at": instant.isoformat() if instant else None,
                "remind_before_minutes": minutes,
            }
        )
    question = "要提前多久提醒？"
    if choices[0]["disabled"]:
        question = "默认提前 1 小时的时间已过，请选更短的时间或不提醒。"
    return _reply(f"{option['label']}。{question}", stage="reminder", choices=choices), None


def _process(owner, request_id, payload=None, choice=None):
    fingerprint = sha256(payload.model_dump_json().encode()).hexdigest() if payload else None
    with db._conn() as conn:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute(
            "SELECT input,result FROM captures WHERE user_id=? AND request_id=?",
            (owner, request_id),
        ).fetchone()
        if row:
            if payload and row["input"] != fingerprint:
                raise HTTPException(409, "request_id_conflict")
            previous = json.loads(row["result"])
            if choice is None or previous["status"] == "created":
                return previous, None
            stage = previous.get("stage", "item")
            if stage == "reminder" and choice.stage == "item":
                # A retried item selection cannot also select a reminder.
                return previous, None
            options = previous.get("choices", [])
            if choice.stage != stage or choice.option > len(options):
                raise HTTPException(422, "invalid_choice")
            selected = options[choice.option - 1]
            result, event = _finish_option(conn, owner, selected, stage)
            result["request_id"] = request_id
            conn.execute(
                "UPDATE captures SET result=? WHERE user_id=? AND request_id=?",
                (json.dumps(result, ensure_ascii=False), owner, request_id),
            )
            return result, event
        if payload is None:
            raise HTTPException(404, "capture_not_found")
        try:
            plan = _plan(payload.text, datetime.now(ZoneInfo(payload.timezone)))
        except (ValueError, OverflowError):
            plan = _reply("时间格式有误，请重新描述。")
        options = plan.get("options", [])
        event = None
        if len(options) == 1:
            result, event = _finish_option(conn, owner, options[0], "item")
        elif options:
            result = _reply("请确认要添加哪一项。", choices=options)
        else:
            result = plan
        result["request_id"] = request_id
        if result["status"] != "not_action":
            conn.execute(
                "INSERT INTO captures VALUES (?,?,?,?)",
                (
                    owner,
                    request_id,
                    fingerprint,
                    json.dumps(result, ensure_ascii=False),
                ),
            )
        return result, event


async def _notify(request, owner, event):
    if event:
        await request.app.state.push_service.notify(*event, user_id=owner)


@router.post("")
async def capture(
    payload: CaptureInput, request: Request, owner: int = Depends(current_session_user)
):
    result, event = await run_in_threadpool(_process, owner, payload.request_id, payload)
    await _notify(request, owner, event)
    return result


@router.post("/{request_id}/confirm")
async def confirm(
    request_id: str,
    payload: CaptureChoice,
    request: Request,
    owner: int = Depends(current_session_user),
):
    result, event = await run_in_threadpool(_process, owner, request_id, choice=payload)
    await _notify(request, owner, event)
    return result
