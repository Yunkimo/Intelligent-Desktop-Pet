"""课表图片视觉识别：httpx 调用 OpenAI 兼容 vision API（如硅基流动 Qwen3-VL）。

模型只负责"照抄"两个区域：表格格子里的课程（grid）与底部备注（notes）；
备注信息与格子的合并由本模块确定性完成，模型不判断课程该放哪一格。
视觉模型存在偶发臆造（如把备注课程塞进空格子），因此并行识别两次取交集：
真实课程两次都在，偶发臆造条目只出现一次，交集天然过滤。
"""

import asyncio
import base64
import json
import re

import httpx
from pydantic import ValidationError

from . import config
from .schemas import CourseIn

# 图片大小上限（小程序端已压缩，正常远小于此）
MAX_IMAGE_BYTES = 10 * 1024 * 1024

# 视觉模型推理较慢（单次 30-70s，高峰期可能更久）；超时不重试，
# 双路并行中一路超时走单路降级，最坏约 120s 内出结果
_VISION_TIMEOUT = httpx.Timeout(120.0, connect=10.0)


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
- start_time / end_time: 按节次换算的 "HH:MM"（规则见下）
- location: 教室（没有则空字符串 ""）
- teacher: 教师名（格子内标注的，没有则空字符串 ""）
- weeks: 周次整数数组（未标注则省略该字段）

## 时间规则（最重要）
- 原图「节次」列通常只标注节次号（如 1-2、3-4），没有具体时间。
- 必须按下述固定映射把节次换算成时间，禁止臆造任何其它时间
  （尤其禁止 12:00、13:00、14:00、18:00 等图中不存在的时间）：
  第1-2节 -> 08:00-09:40；第3-4节 -> 10:00-11:40；第5-6节 -> 14:00-15:40；
  第7-8节 -> 16:00-17:40；第9-10节 -> 19:00-20:40；第11-12节 -> 21:00-22:40。
- 若图片中某处明确标注了具体时间，以图片标注为准。

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
    if isinstance(value, str) and value.isdigit():
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
        text = value.strip()
        parity = _PARITY_RE.search(text)
        text = _PARITY_RE.sub("", text).replace("周", "").strip()
        weeks: list[int] = []
        for part in re.split(r"[,，、/;\s]+", text):
            if not part:
                continue
            match = re.fullmatch(r"(\d+)-(\d+)", part)
            if match:
                weeks.extend(range(int(match.group(1)), int(match.group(2)) + 1))
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


def _course_slot_key(course: dict) -> tuple:
    """两轮识别一致性比较键：同名同天同时段视为同一门课。"""
    return (course["name"], course["day_of_week"], course["start_time"], course["end_time"])


def _intersect_courses(run_a: list[dict], run_b: list[dict]) -> tuple[list[dict], int]:
    """取两轮识别结果交集，返回 (保留课程, 被过滤条目数)。

    偶发臆造条目只出现在单轮，交集自然过滤；周次冲突时优先取非 None 的一侧。"""
    by_slot: dict[tuple, list[dict]] = {}
    for course in run_b:
        by_slot.setdefault(_course_slot_key(course), []).append(course)
    final: list[dict] = []
    dropped = 0
    for course in run_a:
        key = _course_slot_key(course)
        matches = by_slot.get(key)
        if not matches:
            dropped += 1
            continue
        match = matches.pop(0)
        if not course.get("weeks") and match.get("weeks"):
            course = {**course, "weeks": match["weeks"]}
        final.append(course)
    dropped += sum(len(v) for v in by_slot.values())
    return final, dropped


async def _call_vision(image_bytes: bytes, mime: str) -> str:
    """单次 chat/completions 调用，返回 message.content 文本。"""
    url = config.LLM_BASE_URL.rstrip("/") + "/chat/completions"
    payload = {
        "model": config.LLM_VISION_MODEL,
        "messages": build_messages(image_bytes, mime),
        "temperature": 0,
        "max_tokens": 4096,
    }
    headers = {"Authorization": f"Bearer {config.LLM_API_KEY}"}
    last_error: httpx.HTTPStatusError | None = None
    # 上游偶发 5xx（图片请求的服务端抖动），重试一次
    for attempt in range(2):
        try:
            async with httpx.AsyncClient(timeout=_VISION_TIMEOUT) as client:
                response = await client.post(url, json=payload, headers=headers)
                if response.status_code >= 500:
                    last_error = httpx.HTTPStatusError(
                        f"上游返回 HTTP {response.status_code}",
                        request=response.request,
                        response=response,
                    )
                    await asyncio.sleep(3)
                    continue
                response.raise_for_status()
                data = response.json()
                break
        except httpx.TimeoutException as exc:
            raise VisionTimeout("视觉模型响应超时") from exc
        except httpx.HTTPStatusError as exc:
            # 只透出状态码，不透出响应正文（可能冗长且含未知内容）
            raise VisionError(f"上游返回 HTTP {exc.response.status_code}") from exc
        except (httpx.HTTPError, ValueError) as exc:
            raise VisionError(f"请求视觉模型失败：{exc}") from exc
    else:
        assert last_error is not None
        raise VisionError(f"上游返回 HTTP {last_error.response.status_code}")
    content = data["choices"][0]["message"]["content"]
    if not isinstance(content, str):
        raise VisionError("模型返回结构异常")
    return content


async def parse_schedule_image(image_bytes: bytes, mime: str) -> dict:
    """识别课表图片，返回 {"courses": [dict], "skipped": int}（不落库）。

    并行识别两次取交集消除偶发臆造；模型输出 grid（格子课程）与 notes（备注课程）；
    备注按课程名确定性合并补充教师/周次，无格子对应的备注跳过。"""
    if not is_configured():
        raise VisionNotConfigured()
    mime = mime if mime.startswith("image/") else "image/jpeg"
    results = await asyncio.gather(
        _call_vision(image_bytes, mime), _call_vision(image_bytes, mime), return_exceptions=True
    )
    texts = [r for r in results if isinstance(r, str)]
    if not texts:
        # 两路全部失败：抛首个异常（VisionTimeout/VisionError）
        raise results[0]
    runs: list[list[dict]] = []
    skipped = 0
    notes_pool: dict[str, dict] = {}
    for text in texts:
        payload = extract_json_object(text)
        raw_grid = payload.get("grid")
        if not isinstance(raw_grid, list):
            raise VisionError("模型输出缺少 grid 数组")
        raw_notes = payload.get("notes") if isinstance(payload.get("notes"), list) else []
        courses, run_skipped = _parse_grid_items(raw_grid)
        runs.append(courses)
        skipped += run_skipped
        for raw in raw_notes:
            if not isinstance(raw, dict) or not isinstance(raw.get("name"), str):
                continue
            name = raw["name"].strip()
            if not name:
                continue
            notes_pool.setdefault(
                name,
                {
                    "name": name,
                    "teacher": raw.get("teacher") if isinstance(raw.get("teacher"), str) else "",
                    "weeks": _coerce_weeks(raw.get("weeks")),
                },
            )
    if len(runs) == 1:
        # 一路失败时降级为单路结果（无交集可做；确认弹窗仍由用户把关）
        courses, dropped = runs[0], 0
    else:
        courses, dropped = _intersect_courses(runs[0], runs[1])
    skipped += dropped
    courses, skipped = _merge_notes(courses, list(notes_pool.values()), skipped)
    return {"courses": courses, "skipped": skipped}
