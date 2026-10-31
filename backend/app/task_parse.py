"""将自然语言拆为可确认草稿。所有时间推断均基于请求中的参考时刻。"""

import asyncio
import re
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import HTTPException
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator

from . import config, vision


class TextInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    text: str = Field(min_length=1, max_length=2000)
    reference_at: AwareDatetime
    timezone: str = Field(max_length=80)

    @field_validator("timezone")
    @classmethod
    def known_timezone(cls, value):
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError):
            raise ValueError("无效的 IANA 时区") from None
        return value


DAY = re.compile(r"\d{4}-\d{2}-\d{2}|今天|明天|后天|昨天|(?:本|下)?周[一二三四五六日天]")
CLOCK = re.compile(
    r"(上午|早上|中午|下午|晚上|凌晨)?\s*(\d{1,2}|[一二两三四五六七八九十]{1,3})(?:[:：](\d{2})|点(?:(半)|(\d{1,2})分)?)"
)
DIGITS = dict(zip("一二三四五六七八九", range(1, 10)))
DIGITS["两"] = 2


def hour_number(word):
    if word.isdecimal():
        return int(word)
    if word in DIGITS:
        return DIGITS[word]
    if word.count("十") == 1:
        tens, ones = word.split("十")
        if (not tens or tens in DIGITS) and (not ones or ones in DIGITS):
            return DIGITS.get(tens, 1) * 10 + DIGITS.get(ones, 0)
    return 99


def resolve_day(token, today):
    offsets = {"昨天": -1, "今天": 0, "明天": 1, "后天": 2}
    if token in offsets:
        return today + timedelta(days=offsets[token])
    if token.startswith(("本周", "下周")):
        dow = "一二三四五六日".index(token[-1].replace("天", "日"))
        return today + timedelta(days=dow - today.weekday() + (7 if token.startswith("下") else 0))
    if token.startswith("周"):
        return None
    return date.fromisoformat(token)


def draft(source, now):
    original = source
    fields = re.split(r"备注[：:]", source, maxsplit=1)
    source = fields[0].strip()
    note = fields[1].strip() if len(fields) == 2 else ""
    flags = []
    days = list(DAY.finditer(source))
    clocks = list(CLOCK.finditer(source))
    day = None
    if len(days) == 1:
        try:
            day = resolve_day(days[0].group(), now.date())
        except (ValueError, OverflowError):
            pass
    if not day:
        flags.append("date")
    remind = "提醒" in source and not re.search(
        r"不(?:用|要|必|需(?:要)?)?提醒|取消提醒|无需提醒", source
    )
    due = bool(re.search(r"截止|之前|以前|前交|前提交", source))
    instant = None
    if len(clocks) == 1 and day:
        period, hour, mins, half, minute = clocks[0].groups()
        h = hour_number(hour)
        m = int(mins or minute or (30 if half else 0))
        if period and 1 <= h <= 12:
            if period in ("下午", "晚上") or (period == "中午" and h < 6):
                h = h % 12 + 12
            elif h == 12 and period in ("凌晨", "早上", "上午"):
                h = 0
        elif period:
            h = 99
        # 省略上午/下午的中文“三点”须确认，24 小时制 03:00 含义明确。
        if h < 24 and m < 60 and (period or mins is not None or h > 12):
            instant = datetime.combine(day, time(h, m), tzinfo=now.tzinfo)
    if remind and instant is None:
        flags.append("remind_at")
    if not remind and (clocks or re.search("上午|下午|晚上|凌晨", source)):
        flags.append("time")
    if (instant and instant < now) or (day and day < now.date()):
        flags.append("past")
    title = source
    if len(days) == 1 and day:
        title = re.sub(re.escape(days[0].group()) + r"(?:之前|以前|前)?", "", title, count=1)
    if instant and len(clocks) == 1:
        title = title.replace(clocks[0].group(), "", 1)
    title = (
        re.sub(r"^(?:(?:请)?提醒我|截止到|截止|然后|另外|并且|同时|，|,|\s)+", "", title).strip(
            " ,，"
        )
        or source
    )
    return {
        "title": title,
        "note": note,
        "source": original,
        "due_at": day.isoformat() if day and (due or not remind) else None,
        "remind_at": instant.isoformat() if remind and instant else None,
        "needs_confirmation": flags,
    }


async def parse_tasks(payload):
    now = payload.reference_at.astimezone(ZoneInfo(payload.timezone))
    parts = [v.strip() for v in re.split(r"[；;。\n]+", payload.text) if v.strip()]
    if not parts or len(parts) > 20:
        raise HTTPException(422, detail="请输入 1～20 个事项")
    # 仅将未拆开的复合事项交给可选文本模型断句；要求逐字保留原文与顺序。
    if len(parts) == 1 and re.search(r"然后|另外|并且|同时", parts[0]) and config.LLM_TEXT_MODEL:
        if not config.LLM_API_KEY or not config.LLM_BASE_URL:
            raise HTTPException(503, detail="未配置文本模型凭据")
        messages = [
            {
                "role": "system",
                "content": '把文本按事项切分，逐字保留内容和顺序，包含连接词。仅返回 {"parts":["原文片段"]}。',
            },
            {"role": "user", "content": parts[0]},
        ]
        try:
            result = await asyncio.wait_for(
                vision.chat_content(config.LLM_TEXT_MODEL, messages), config.PARSE_TIMEOUT_SECONDS
            )
            segments = vision.extract_json_object(result).get("parts")
            if (
                not isinstance(segments, list)
                or not 1 <= len(segments) <= 20
                or not all(isinstance(s, str) and s.strip() for s in segments)
                or "".join(segments) != parts[0]
            ):
                raise vision.VisionError("文本模型输出无效")
            parts = segments
        except (asyncio.TimeoutError, vision.VisionTimeout):
            raise HTTPException(504, detail={"code": "parse_timeout"}) from None
        except vision.VisionRateLimited:
            raise HTTPException(429, detail={"code": "rate_limited"}) from None
        except vision.VisionError:
            raise HTTPException(502, detail={"code": "invalid_upstream"}) from None
    if not config.LLM_TEXT_MODEL:
        parts = [
            part.strip()
            for segment in parts
            for part in re.split(r"然后|另外|并且", segment)
            if part.strip()
        ]
    if not 1 <= len(parts) <= 20:
        raise HTTPException(422, detail="请输入 1～20 个事项")
    return {"drafts": [draft(p, now) for p in parts]}
