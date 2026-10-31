"""课表图片视觉识别：httpx 调用 OpenAI 兼容 vision API（如硅基流动 Qwen3-VL）。

模型只负责"照抄"两个区域：表格格子里的课程（grid）与底部备注（notes）；
备注信息与格子的合并由本模块确定性完成，模型不判断课程该放哪一格。
"""

import asyncio
import base64
import json
import logging
import re
import time

import httpx
from pydantic import ValidationError

from . import config
from .schemas import CourseIn

# 图片大小上限（小程序端已压缩，正常远小于此）
MAX_IMAGE_BYTES = 10 * 1024 * 1024

logger = logging.getLogger(__name__)


class VisionNotConfigured(Exception):
    """未配置 LLM_API_KEY / LLM_BASE_URL / LLM_VISION_MODEL（对外 503）。"""


class VisionError(Exception):
    """视觉模型调用或输出解析失败（对外 502）。"""


class VisionTimeout(VisionError):
    """视觉模型响应超时（对外 504）。"""


VISION_SYSTEM_PROMPT = """你是课表识别助手。分析用户上传的大学课表图片。
严格只输出一个 JSON 对象，不要输出任何其它文字、解释或 Markdown 代码块。
对象格式：{"grid": [课程...], "notes": [备注课程...]}

## grid 数组：表格主体格子中的课程
只识别表格主体（星期×节次）每个格子里的课程，**忽略底部「备注」行**。
每个格子对应一条记录；空格子不输出；格子内多门课（按周次交替）拆成多条记录，
各自带正确周次；同一课程在同一天同一节次只允许一条记录，禁止重复。

每条记录字段：
- name: 课程名称
- day_of_week: 整数 1-7（1=周一…7=周日，注意表头可能从周日开始）
- start_time / end_time: 仅抄图中明确标出的 HH:MM，否则两者均为 null。
- slot: 抄录节次标签，无标签时写“第N行”（从第一行课程计数），禁止将节次换算为固定时间。
- location / teacher: 抄录地点和教师；未标注写空字符串。
- weeks: 抄录周次（包括单双周、离散周），未标注省略。

## 周数规则
- 完整照抄，禁止缩窄范围：如「3-18周」必须输出 3-18，不能写成 3-14。
- 多区间合并为一个数组：「1-9,12-18周」-> [1,2,...,9,12,13,...,18]。
- 「11-18(单周)」-> 只含奇数周 [11,13,15,17]；「双周」-> 只含偶数周。
- 「7,11周」-> [7,11]。未标注周次 -> 省略 weeks 字段。

## notes 数组：底部备注区的课程（只照抄，不安排位置）
底部「备注」行每门课程一条记录，字段：
- name: 课程名称
- teacher: 教师名（备注中标注的）
- weeks: 周次整数数组（按上面的周数规则展开；未标注则省略）
**禁止为 notes 中的课程臆造 day_of_week、start_time、end_time、location**——
这些字段一律不输出，由系统与表格格子按课程名合并。
「点击查看实践实验课表」等链接文字不是课程，忽略。

## 输出前自查
1. grid 中每门课时间与节次严格对应；2. 周数与原图完全一致；
3. grid 无重复记录；4. grid 课程总数与图中非空格子数一致；
5. notes 只含备注区真实列出的课程。

输出示例：
{"grid":[{"name":"高等数学","day_of_week":1,"start_time":"08:00","end_time":"09:40","location":"A101","teacher":"张三","weeks":[1,2,3]}],"notes":[{"name":"形势与政策","teacher":"李四","weeks":[7,11]}]}"""

_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL)


def is_configured() -> bool:
    return bool(config.LLM_API_KEY and config.LLM_BASE_URL and config.LLM_VISION_MODEL)


def to_data_url(image_bytes: bytes, mime: str) -> str:
    """图片字节转 base64 data URL（vision API 的 image_url 格式）。"""
    return f"data:{mime};base64,{base64.b64encode(image_bytes).decode('ascii')}"


def build_messages(image_bytes: bytes, mime: str) -> list[dict]:
    """构造 OpenAI 兼容 vision 消息（system + user 图文）。"""
    return [
        {"role": "system", "content": VISION_SYSTEM_PROMPT},
        {
            "role": "user",
            "content": [
                {"type": "image_url", "image_url": {"url": to_data_url(image_bytes, mime)}},
                {"type": "text", "text": "请识别这张课表图片，按格式输出 JSON 对象。"},
            ],
        },
    ]


def extract_json_object(text: str) -> dict:
    """从模型输出提取首个 JSON 对象：剥代码围栏，取首 { 到尾 }。失败抛 VisionError。"""
    if not text:
        raise VisionError("模型返回内容为空")
    fence = _FENCE_RE.search(text)
    candidate = fence.group(1).strip() if fence else text
    start, end = candidate.find("{"), candidate.rfind("}")
    if start == -1 or end <= start:
        raise VisionError("模型输出中没有 JSON 对象")
    try:
        data = json.loads(candidate[start : end + 1])
    except json.JSONDecodeError as exc:
        raise VisionError(f"模型输出不是合法 JSON：{exc.msg}") from exc
    if not isinstance(data, dict):
        raise VisionError("模型输出不是 JSON 对象")
    return data


def _coerce_day_of_week(value):
    """'3' → 3，容忍模型把整数写成字符串。"""
    if isinstance(value, str) and len(value) <= 2 and value.isascii() and value.isdigit():
        return int(value)
    return value


def _pad_time(value):
    """'8:00' → '08:00'，容忍模型漏写前导零。"""
    if isinstance(value, str) and re.fullmatch(r"\d{1,2}:\d{2}", value):
        hh, mm = value.split(":")
        return f"{int(hh):02d}:{mm}"
    return value


_PARITY_RE = re.compile(r"[（(]?(单周|双周)[)）]?")


def _coerce_weeks(value):
    """weeks 宽容解析：int / 数组 / '1-16' / '1-9,12-18' / '11-18(单周)' / '7,11周'。

    支持逗号/顿号/斜杠/分号分隔的多区间；单周只保留奇数周、双周只保留偶数周；
    无法解析返回 None（全周）。"""
    if value is None:
        return None
    if isinstance(value, int):
        return [value]
    if isinstance(value, list) and all(isinstance(v, int) for v in value):
        return value
    if isinstance(value, str):
        if len(value) > 200:
            return None
        text = value.strip()
        parity = _PARITY_RE.search(text)
        text = _PARITY_RE.sub("", text).replace("周", "").strip()
        weeks: list[int] = []
        for part in re.split(r"[,，、/;\s]+", text):
            if not part:
                continue
            match = re.fullmatch(r"(\d+)-(\d+)", part)
            if match:
                lo, hi = map(int, match.groups())
                if not 1 <= lo <= hi <= 53:
                    return None
                weeks.extend(range(lo, hi + 1))
            elif part.isdigit():
                weeks.append(int(part))
            else:
                return None
        if parity:
            keep_odd = parity.group(1) == "单周"
            weeks = [w for w in weeks if (w % 2 == 1) == keep_odd]
        return weeks or None
    return None


def _dedupe_key(course: dict) -> tuple:
    """识别结果去重键：同一天同一时段同名同周次视为重复。"""
    return (
        course["name"],
        course["day_of_week"],
        course["start_time"],
        course["end_time"],
        tuple(course.get("weeks") or []),
    )


def _parse_grid_items(raw_items: list) -> tuple[list[dict], int]:
    """校验并归一化 grid 数组；返回 (有效课程列表, 无效条目数)。"""
    courses: list[dict] = []
    skipped = 0
    seen: set[tuple] = set()
    for raw in raw_items:
        if not isinstance(raw, dict):
            skipped += 1
            continue
        item = {
            "name": raw.get("name"),
            "day_of_week": _coerce_day_of_week(raw.get("day_of_week")),
            "start_time": _pad_time(raw.get("start_time")),
            "end_time": _pad_time(raw.get("end_time")),
            "location": raw.get("location", ""),
            "teacher": raw.get("teacher", ""),
            "weeks": _coerce_weeks(raw.get("weeks")),
        }
        try:
            course = CourseIn.model_validate(item).model_dump()
        except ValidationError:
            skipped += 1
            continue
        key = _dedupe_key(course)
        if key in seen:
            skipped += 1
            continue
        seen.add(key)
        courses.append(course)
    return courses, skipped


def _merge_notes(courses: list[dict], raw_notes: list, skipped: int) -> tuple[list[dict], int]:
    """把备注信息确定性合并进格子课程：按课程名匹配补教师/周次；无匹配的备注跳过。"""
    if not raw_notes:
        return courses, skipped
    notes: list[dict] = []
    for raw in raw_notes:
        if not isinstance(raw, dict) or not raw.get("name") or not isinstance(raw["name"], str):
            skipped += 1
            continue
        notes.append(
            {
                "name": raw["name"].strip(),
                "teacher": raw.get("teacher") if isinstance(raw.get("teacher"), str) else "",
                "weeks": _coerce_weeks(raw.get("weeks")),
            }
        )
    for note in notes:
        matched = [c for c in courses if c["name"] == note["name"]]
        if not matched:
            # 备注课程在表格中没有对应格子：不臆造位置，直接跳过
            skipped += 1
            continue
        for course in matched:
            if not course["teacher"] and note["teacher"]:
                course["teacher"] = note["teacher"]
            if not course["weeks"] and note["weeks"]:
                course["weeks"] = note["weeks"]
    return courses, skipped


async def chat_content(model: str, messages: list[dict]) -> str:
    url = config.LLM_BASE_URL.rstrip("/") + "/chat/completions"
    try:
        async with httpx.AsyncClient(timeout=config.PARSE_TIMEOUT_SECONDS) as client:
            response = await client.post(
                url,
                headers={"Authorization": "Bearer " + config.LLM_API_KEY},
                json={"model": model, "messages": messages, "temperature": 0, "max_tokens": 4096},
            )
            if response.status_code == 429:
                raise VisionRateLimited("模型服务限流")
            response.raise_for_status()
            content = response.json()["choices"][0]["message"]["content"]
    except httpx.TimeoutException:
        raise VisionTimeout("模型响应超时") from None
    except (httpx.HTTPError, ValueError, TypeError, KeyError, IndexError):
        raise VisionError("模型不可达或响应格式错误") from None
    if not isinstance(content, str) or len(content) > 65536:
        raise VisionError("模型返回内容无效")
    return content


class VisionRateLimited(VisionError):
    """模型服务限流。"""


async def _call_vision(image_bytes: bytes, mime: str) -> str:
    return await chat_content(config.LLM_VISION_MODEL, build_messages(image_bytes, mime))


def _valid_clock(value):
    return isinstance(value, str) and re.fullmatch(r"(?:[01][0-9]|2[0-3]):[0-5][0-9]", value)


async def parse_schedule_image(image_bytes: bytes, mime: str) -> dict:
    if not is_configured():
        raise VisionNotConfigured()
    started = time.monotonic()
    try:
        content = await asyncio.wait_for(
            _call_vision(image_bytes, mime or "image/jpeg"), config.PARSE_TIMEOUT_SECONDS
        )
    except asyncio.TimeoutError:
        raise VisionTimeout("识别超时") from None
    parsed_at = time.monotonic()
    payload = extract_json_object(content)
    grid, notes = payload.get("grid"), payload.get("notes", [])
    if (
        not isinstance(grid, list)
        or not isinstance(notes, list)
        or len(grid) + len(notes) > 150
        or len(grid) > 100
    ):
        raise VisionError("模型条目过多或缺少有效 grid/notes")
    ready, pending, warnings = [], [], []
    for index, row in enumerate(grid, 1):
        if (
            not isinstance(row, dict)
            or not isinstance(row.get("name"), str)
            or not row["name"].strip()
        ):
            warnings.append(f"第{index}项课程名称无效，请核对原图")
            continue
        start, end = (_pad_time(row.get(k)) for k in ("start_time", "end_time"))
        weeks = _coerce_weeks(row.get("weeks"))
        invalid_weeks = row.get("weeks") not in (None, "", []) and not (
            weeks and all(type(w) is int and 1 <= w <= 53 for w in weeks)
        )
        invalid_time = not (_valid_clock(start) and _valid_clock(end) and start < end)
        weekday = _coerce_day_of_week(row.get("day_of_week"))
        invalid_day = type(weekday) is not int or not 1 <= weekday <= 7
        if invalid_time or invalid_weeks or invalid_day:
            warnings.append(f"第{index}项需要确认")
            pending.append(
                {
                    "name": row["name"],
                    "teacher": row.get("teacher", ""),
                    "location": row.get("location", ""),
                    "day_of_week": None if invalid_day else weekday,
                    "slot": row.get("slot"),
                    "start_time": None if invalid_time else start,
                    "end_time": None if invalid_time else end,
                    "weeks": None if invalid_weeks else weeks,
                    "needs_confirmation": (["time"] if invalid_time else [])
                    + (["weeks"] if invalid_weeks else [])
                    + (["day_of_week"] if invalid_day else []),
                }
            )
        else:
            ready.append(row)
    courses, skipped = _parse_grid_items(ready)
    _, skipped = _merge_notes(courses + pending, notes, skipped)
    if skipped:
        warnings.append(f"{skipped}项重复、无效或未能匹配备注，请核对")
    logger.info(
        "vision model_ms=%.0f parse_ms=%.0f",
        (parsed_at - started) * 1000,
        (time.monotonic() - parsed_at) * 1000,
    )
    return {
        "courses": courses,
        "pending_courses": pending,
        "skipped": skipped + len(grid) - len(ready) - len(pending),
        "warnings": warnings,
    }
