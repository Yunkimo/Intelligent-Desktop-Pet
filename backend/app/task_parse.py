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


DAY = re.compile(
    r"\d{4}-\d{2}-\d{2}|(?:今|明|后|昨)天|(?:今|明|后|昨)晚|(?:本|下)?周[一二三四五六日天]"
)
CLOCK = re.compile(
    r"(上午|早上|中午|下午|晚上|凌晨)?\s*(\d{1,2}|[一二两三四五六七八九十]{1,3})(?:[:：](\d{2})|点(?:(半)|(\d{1,2})分)?)"
)
# 相对时间：「15分钟后」「两小时后」「半小时后」
OFFSET = re.compile(
    r"(?P<num>\d{1,2}|[一二两三四五六七八九十]{1,3}|半)(?:个)?(?P<unit>分钟|小时)(?:钟)?后"
)
DUE_MARKERS = re.compile(r"截止|之前|以前|前交|前提交")
REMIND_NEG = re.compile(r"不(?:用|要|必|需(?:要)?)?提醒|取消提醒|无需提醒")
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
    offsets = {
        "昨天": -1,
        "今天": 0,
        "明天": 1,
        "后天": 2,
        "昨晚": -1,
        "今晚": 0,
        "明晚": 1,
        "后天晚": 2,
    }
    if token in offsets:
        return today + timedelta(days=offsets[token])
    if token.startswith(("本周", "下周")):
        dow = "一二三四五六日".index(token[-1].replace("天", "日"))
        return today + timedelta(days=dow - today.weekday() + (7 if token.startswith("下") else 0))
    if token.startswith("周"):
        return None
    return date.fromisoformat(token)


def offset_delta(match):
    """「15分钟后」「两小时后」「半小时后」→ timedelta；无法解析返回 None。"""
    num = match.group("num")
    unit = match.group("unit")
    if num == "半":
        minutes = 30
    else:
        value = hour_number(num)
        if value == 99:
            return None
        minutes = value if unit == "分钟" else value * 60
    return timedelta(minutes=minutes)


def _split_commas(part):
    """逗号子句拆分：无时间表达的子句并入前一句；带截止标记且无「提醒」的
    子句是前一句的截止说明，也并入前一句（同一事项）；否则视为独立事项。"""
    segments = [s.strip() for s in re.split(r"[，,]", part) if s.strip()]
    if len(segments) <= 1:
        return [part]
    merged = [segments[0]]
    for segment in segments[1:]:
        has_time = bool(DAY.search(segment) or CLOCK.search(segment) or OFFSET.search(segment))
        is_due_clause = bool(DUE_MARKERS.search(segment)) and not (
            "提醒" in segment and not REMIND_NEG.search(segment)
        )
        if not has_time or is_due_clause:
            merged[-1] += "，" + segment
        else:
            merged.append(segment)
    return merged


def draft(source, now, anchor=None):
    """把一条子句解析为草稿；返回 (草稿, 本句得到的时刻)（时刻供后续相对时间锚定）。

    与 B7 原契约的差异（向后兼容，见 docs/b7-parsing.md 补充）：
    - 出现多个日期词时：第一个作提醒日期，出现截止标记时最后一个作截止日期；
    - 出现多个时刻时：取第一个明确时刻（带时段或 24 小时制）作提醒时刻，
      截止子句里的时刻因 due_at 只有日期粒度而不入库、不再误报「提醒时刻不明」；
    - 支持「今晚/明晚/昨晚/后天晚」日期词；晚间的裸时刻按晚上解释（今晚六点→18:00）；
    - 支持「15分钟后/两小时后/半小时后」相对时间，锚点为前文最后一个时刻或参考时刻。
    """
    original = source
    fields = re.split(r"备注[：:]", source, maxsplit=1)
    source = fields[0].strip()
    note = fields[1].strip() if len(fields) == 2 else ""
    flags = []
    days = list(DAY.finditer(source))
    clocks = list(CLOCK.finditer(source))
    offsets = list(OFFSET.finditer(source))
    remind = "提醒" in source and not REMIND_NEG.search(source)
    due = bool(DUE_MARKERS.search(source))
    day = None
    due_day = None
    evening = bool(days and days[0].group().endswith("晚"))
    if days:
        try:
            day = resolve_day(days[0].group(), now.date())
        except (ValueError, OverflowError):
            day = None
        if due and len(days) > 1:
            try:
                due_day = resolve_day(days[-1].group(), now.date())
            except (ValueError, OverflowError):
                due_day = None
    if day is None and not offsets:
        flags.append("date")
    instant = None
    # 提醒时刻：取第一个明确时刻（带时段/带分钟/24 小时制；晚间裸时刻按晚上解释）。
    if clocks and day:
        for match in clocks:
            period, hour, mins, half, minute = match.groups()
            h = hour_number(hour)
            m = int(mins or minute or (30 if half else 0))
            if period and 1 <= h <= 12:
                if period in ("下午", "晚上") or (period == "中午" and h < 6):
                    h = h % 12 + 12
                elif h == 12 and period in ("凌晨", "早上", "上午"):
                    h = 0
            elif period:
                continue  # 不认识的时段词：试下一个时刻
            # 省略上午/下午的中文“三点”须确认，24 小时制 03:00 含义明确；
            # 但「今晚三点」这类晚间语境是明确的。
            if h < 24 and m < 60 and (period or mins is not None or h > 12 or evening):
                if evening and h < 12:
                    h += 12
                instant = datetime.combine(day, time(h, m), tzinfo=now.tzinfo)
                break
    # 相对时间：锚点为本句明确时刻；没有则用前文最后一个时刻；再没有用参考时刻。
    if offsets and instant is None:
        base = anchor
        if base is None:
            if day:
                base = datetime.combine(day, time(now.hour, now.minute), tzinfo=now.tzinfo)
            else:
                base = now
        for match in offsets:
            delta = offset_delta(match)
            if delta is None:
                continue
            base = base + delta
            instant = base
        if instant is not None:
            day = instant.date()  # 相对时刻自带日期，不再标日期不明
    if remind and instant is None:
        flags.append("remind_at")
    if not remind and (clocks or offsets or re.search("上午|下午|晚上|凌晨", source)):
        flags.append("time")
    if (
        (instant and instant < now)
        or (day and day < now.date())
        or (due_day and due_day < now.date())
    ):
        flags.append("past")
    title = source
    # 多日期且存在截止子句：标题截到最后一个日期词之前（截止子句只贡献日期）
    if due_day is not None:
        title = title[: days[-1].start()].rstrip(" ,，")
    for match in days:
        title = re.sub(re.escape(match.group()) + r"(?:之前|以前|前)?", "", title, count=1)
    for match in clocks:
        title = title.replace(match.group(), "", 1)
    for match in offsets:
        title = title.replace(match.group(), "", 1)
    title = (
        re.sub(
            r"^(?:(?:请)?提醒我|截止到|截止|然后|另外|并且|同时|吃完饭|饭后|，|,|\s)+", "", title
        )
        .strip(" ,，")
        .rstrip("，,")
    ) or source
    title = re.sub(r"[，,]\s*(?:截止到|截止|之前|以前)$", "", title).strip(" ,，") or source
    due_date = due_day or day
    return (
        {
            "title": title,
            "note": note,
            "source": original,
            "due_at": due_date.isoformat() if due_date and (due or not remind) else None,
            "remind_at": instant.isoformat() if remind and instant else None,
            "needs_confirmation": flags,
        },
        instant,
    )


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
    # 逗号子句拆分：同一事项的截止说明并入前句，独立事项拆开
    parts = [segment for part in parts for segment in _split_commas(part)]
    if not 1 <= len(parts) <= 20:
        raise HTTPException(422, detail="请输入 1～20 个事项")
    drafts = []
    last_instant = None
    for part in parts:
        result, instant = draft(part, now, anchor=last_instant)
        drafts.append(result)
        if instant is not None:
            last_instant = instant
    return {"drafts": drafts}
