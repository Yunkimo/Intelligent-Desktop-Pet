"""工具注册表：把后端 REST 与联网能力封装成大模型可调用的 function。

每个工具 = JSON schema（供 function calling）+ callable（执行并返回一句话结果）。
callable 通过闭包绑定到 BackendClient，便于用假后端做单元测试。
"""

import re
from dataclasses import dataclass
from datetime import datetime
from typing import Callable

import httpx

from .backend_client import BackendClient
from .timeparse import normalize_datetime

# 联网工具超时：避免工具循环长时间挂起（7 天预报 + 地理编码两次请求，留 10 秒）
_WEATHER_TIMEOUT_SECS = 10.0

# 天气走 Open-Meteo：免费、免 key、给 7 天预报；wttr.in 的 j1 只有 3 天
_GEOCODE_URL = "https://geocoding-api.open-meteo.com/v1/search"
_FORECAST_URL = "https://api.open-meteo.com/v1/forecast"

# 相对日期 -> 预报数组下标
_WEATHER_DAYS = {
    "今天": 0,
    "今日": 0,
    "现在": 0,
    "明天": 1,
    "明日": 1,
    "后天": 2,
    "大后天": 3,
}
# 整周：返回未来 7 天逐日一行
_WEEK_ALIASES = {"未来一周", "一周", "这周", "本周", "七天", "未来7天", "未来七天", "整周"}

# 周一~周日：中文与数字写法都收
_CN_NUMBERS = {"一": 1, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7}

_WEEKDAY_INDEX = {
    "一": 0,
    "二": 1,
    "三": 2,
    "四": 3,
    "五": 4,
    "六": 5,
    "日": 6,
    "天": 6,
    "1": 0,
    "2": 1,
    "3": 2,
    "4": 3,
    "5": 4,
    "6": 5,
    "7": 6,
}

# WMO 天气代码 -> 中文描述
_WMO_ZH = {
    0: "晴",
    1: "晴间多云",
    2: "多云",
    3: "阴",
    45: "雾",
    48: "冻雾",
    51: "小毛毛雨",
    53: "毛毛雨",
    55: "浓毛毛雨",
    56: "冻毛毛雨",
    57: "浓冻毛毛雨",
    61: "小雨",
    63: "中雨",
    65: "大雨",
    66: "冻雨",
    67: "强冻雨",
    71: "小雪",
    73: "中雪",
    75: "大雪",
    77: "雪粒",
    80: "阵雨",
    81: "中阵雨",
    82: "强阵雨",
    85: "阵雪",
    86: "强阵雪",
    95: "雷雨",
    96: "雷雨伴冰雹",
    99: "强雷雨伴冰雹",
}

_WEEKDAYS = ("周一", "周二", "周三", "周四", "周五", "周六", "周日")


class _WeatherNetError(Exception):
    """联网失败（区别于「查无此城市」）。"""


# 城市 -> (纬度, 经度, 规范名)；同一次运行内复用，避免反复地理编码
_GEO_CACHE: dict[str, tuple[float, float, str]] = {}


def _resolve_day(text: str, dates: list[str]) -> tuple[str, int]:
    """把用户/模型给的日期说法解析成 (类型, 预报下标)。

    支持：今天/明天/后天/大后天、周X/星期X/礼拜X、N天后、ISO 日期、未来一周。
    认不出来时回落到今天，不报错。
    """
    raw = (text or "").strip()
    if not raw:
        return "day", 0
    if any(alias in raw for alias in _WEEK_ALIASES):
        return "week", 0

    match = re.search(r"(\d{4})-(\d{1,2})-(\d{1,2})", raw)
    if match:
        wanted = f"{int(match.group(1)):04d}-{int(match.group(2)):02d}-{int(match.group(3)):02d}"
        if wanted in dates:
            return "date", dates.index(wanted)
        return "day", 0

    # 长的先匹配，「大后天」不能被「后天」抢先
    for key in sorted(_WEATHER_DAYS, key=len, reverse=True):
        if key in raw:
            return "day", _WEATHER_DAYS[key]

    match = re.search(r"(?:周|星期|礼拜)([一二三四五六日天1-7])", raw)
    if match:
        target = _WEEKDAY_INDEX.get(match.group(1))
        if target is not None:
            for index, date in enumerate(dates):
                try:
                    if datetime.strptime(date, "%Y-%m-%d").weekday() == target:
                        return "weekday", index
                except (TypeError, ValueError):
                    continue
        return "day", 0

    match = re.search(r"(\d{1,2})\s*月\s*(\d{1,2})\s*[日号]", raw)
    if match:
        month, day_of_month = int(match.group(1)), int(match.group(2))
        for index, date in enumerate(dates):
            try:
                parsed = datetime.strptime(date, "%Y-%m-%d")
            except (TypeError, ValueError):
                continue
            if parsed.month == month and parsed.day == day_of_month:
                return "date", index
        return "day", 0

    match = re.search(r"([0-9一二三四五六七])\s*天后", raw)
    if match:
        token = match.group(1)
        offset = int(token) if token.isdigit() else _CN_NUMBERS.get(token, 0)
        return "day", min(offset, max(len(dates) - 1, 0))

    return "day", 0


def _weekday(date: str) -> str:
    """ISO 日期转「周一」这类中文星期；解析失败返回空串。"""
    try:
        return _WEEKDAYS[datetime.strptime(date, "%Y-%m-%d").weekday()]
    except (TypeError, ValueError):
        return ""


def _span(low: object, high: object) -> str:
    """气温区间；任一缺失时给出可读占位。"""
    if low is None or high is None:
        return "气温未知"
    return f"{low}~{high}°C"


def _weather_text(code: object) -> str:
    """WMO 天气代码转中文；未知代码返回「未知天气」。"""
    try:
        return _WMO_ZH.get(int(code), "未知天气")
    except (TypeError, ValueError):
        return "未知天气"


def _geocode(city: str) -> tuple[float, float, str] | None:
    """把城市名解析成经纬度；找不到返回 None。结果会缓存。"""
    key = city.strip()
    cached = _GEO_CACHE.get(key)
    if cached is not None:
        return cached
    try:
        resp = httpx.get(
            _GEOCODE_URL,
            params={"name": key, "count": 1, "language": "zh"},
            timeout=_WEATHER_TIMEOUT_SECS,
        )
        resp.raise_for_status()
        results = (resp.json() or {}).get("results") or []
    except (httpx.HTTPError, ValueError, AttributeError) as exc:
        raise _WeatherNetError(str(exc)) from exc
    if not results:
        return None
    first = results[0]
    try:
        place = (float(first["latitude"]), float(first["longitude"]), str(first.get("name") or key))
    except (KeyError, TypeError, ValueError):
        return None
    _GEO_CACHE[key] = place
    return place


def _daily_forecast(latitude: float, longitude: float) -> dict | None:
    """取未来 7 天的逐日天气与气温；失败返回 None。"""
    try:
        resp = httpx.get(
            _FORECAST_URL,
            params={
                "latitude": latitude,
                "longitude": longitude,
                "daily": "weather_code,temperature_2m_max,temperature_2m_min",
                "current": "temperature_2m,apparent_temperature",
                "timezone": "auto",
                "forecast_days": 7,
            },
            timeout=_WEATHER_TIMEOUT_SECS,
        )
        resp.raise_for_status()
        data = resp.json()
    except (httpx.HTTPError, ValueError) as exc:
        raise _WeatherNetError(str(exc)) from exc
    return data if isinstance(data, dict) else None


@dataclass
class Tool:
    """单个工具：schema 元数据 + 执行函数 + 执行中的状态文案。"""

    name: str
    description: str
    parameters: dict
    fn: Callable[..., str]
    status: str = "正在处理…"


def tool_schema(tool: Tool) -> dict:
    """转为 OpenAI function calling 所需的 schema 结构。"""
    return {
        "type": "function",
        "function": {
            "name": tool.name,
            "description": tool.description,
            "parameters": tool.parameters,
        },
    }


def _fmt_courses(courses: list[dict]) -> str:
    if not courses:
        return "（还没有课表）"
    parts = []
    for c in courses:
        loc = f" @{c['location']}" if c.get("location") else ""
        parts.append(
            f"周{c.get('day_of_week', '?')} "
            f"{c.get('start_time', '')}-{c.get('end_time', '')} "
            f"{c.get('name', '未命名')}{loc}"
        )
    return "；".join(parts)


def _fmt_tasks(tasks: list[dict]) -> str:
    if not tasks:
        return "（还没有日程）"
    parts = []
    for t in tasks:
        mark = "✓" if t.get("done") else "○"
        due = f"，截止 {t['due_at']}" if t.get("due_at") else ""
        parts.append(f"[#{t.get('id', '?')}]{mark} {t.get('title', '未命名')}{due}")
    return "；".join(parts)


def build_tools(backend: BackendClient, habits=None) -> dict[str, Tool]:
    """构造工具注册表，所有 callable 绑定到给定 backend。

    habits 传入 HabitStore 时额外注册「记住 / 忘记习惯」两个工具；不传则保持
    原有八个工具，方便既有测试与无习惯功能的调用方继续工作。
    """

    def list_courses(**_args) -> str:
        return _fmt_courses(backend.list_courses())

    def list_tasks(**_args) -> str:
        return _fmt_tasks(backend.list_tasks())

    def create_task(
        title: str,
        note: str = "",
        due_at: str | None = None,
        remind_at: str | None = None,
        **_args,
    ) -> str:
        backend.create_task(
            title=title,
            note=note,
            due_at=normalize_datetime(due_at),
            remind_at=normalize_datetime(remind_at),
        )
        return f"已新增日程「{title}」"

    def update_task(task_id: int, **fields) -> str:
        backend.update_task(task_id, **fields)
        return f"已更新日程 #{task_id}"

    def delete_task(task_id: int, **_args) -> str:
        backend.delete_task(task_id)
        return f"已删除日程 #{task_id}"

    def create_reminder(
        title: str, remind_at: str, body: str = "", channel: str = "both", **_args
    ) -> str:
        backend.create_reminder(
            title=title,
            remind_at=normalize_datetime(remind_at),
            body=body,
            channel=channel,
        )
        return f"已设置提醒「{title}」（{remind_at}）"

    def get_weather(city: str, day: str = "今天", **_args) -> str:
        wanted = str(day or "今天").strip()
        try:
            place = _geocode(city)
            if place is None:
                return f"查不到「{city}」这个城市，换个写法试试"
            latitude, longitude, name = place
            data = _daily_forecast(latitude, longitude)
        except _WeatherNetError as exc:
            return f"查天气失败：{exc}"
        if not data:
            return f"查天气失败：{name} 的预报暂时取不到"
        daily = data.get("daily") or {}
        dates = daily.get("time") or []
        if not dates:
            return f"查不到 {name} 的天气"

        kind, offset = _resolve_day(wanted, dates)
        if kind == "week":
            lines = [f"{name} 未来 {len(dates)} 天："]
            for i, date in enumerate(dates):
                desc = _weather_text((daily.get("weather_code") or [None] * len(dates))[i])
                low = (daily.get("temperature_2m_min") or [None] * len(dates))[i]
                high = (daily.get("temperature_2m_max") or [None] * len(dates))[i]
                lines.append(f"{date} {_weekday(date)}：{desc}，{_span(low, high)}")
            return "\n".join(lines)

        index = min(offset, len(dates) - 1)
        date = dates[index]
        desc = _weather_text((daily.get("weather_code") or [None] * len(dates))[index])
        low = (daily.get("temperature_2m_min") or [None] * len(dates))[index]
        high = (daily.get("temperature_2m_max") or [None] * len(dates))[index]
        if kind == "weekday":
            label = _weekday(date) or "今天"
        else:
            label = (
                {0: "今天", 1: "明天", 2: "后天", 3: "大后天"}.get(index)
                or _weekday(date)
                or "今天"
            )
        text = f"{name} {label}（{date}）：{desc}，{_span(low, high)}"
        if index == 0:
            current = data.get("current") or {}
            now = current.get("temperature_2m")
            feel = current.get("apparent_temperature")
            if now is not None:
                text += f"，当前 {now}°C"
                if feel is not None:
                    text += f"（体感 {feel}°C）"
        return text

    def web_search(query: str, **_args) -> str:
        from ddgs import DDGS  # 延迟导入：无网/未装时不影响其它工具

        try:
            results = DDGS().text(query, max_results=5)
        except Exception as exc:  # noqa: BLE001 - 无网/被限流时给出可读反馈而非挂起
            return f"搜索「{query}」失败：{exc}"
        if not results:
            return f"没有搜到与「{query}」相关的结果"
        return "\n".join(f"- {r.get('title', '')}：{r.get('href', '')}" for r in results)

    tools: dict[str, Tool] = {
        "list_courses": Tool(
            "list_courses",
            "查询课表。当主人问今天/明天有什么课、课表安排时调用。",
            {"type": "object", "properties": {}},
            list_courses,
            "正在查询课表…",
        ),
        "list_tasks": Tool(
            "list_tasks",
            "查询日程/待办列表。当主人问有什么安排、待办时调用。",
            {"type": "object", "properties": {}},
            list_tasks,
            "正在查看日程…",
        ),
        "create_task": Tool(
            "create_task",
            "新增一条日程/待办。due_at/remind_at 用 ISO 格式（如 2026-10-11T14:00）。",
            {
                "type": "object",
                "properties": {
                    "title": {"type": "string", "description": "日程标题"},
                    "note": {"type": "string", "description": "备注"},
                    "due_at": {"type": "string", "description": "截止时间"},
                    "remind_at": {"type": "string", "description": "提醒时间"},
                },
                "required": ["title"],
            },
            create_task,
            "正在安排日程…",
        ),
        "update_task": Tool(
            "update_task",
            "修改已有日程。task_id 先从 list_tasks 查得。",
            {
                "type": "object",
                "properties": {
                    "task_id": {"type": "integer", "description": "日程 ID"},
                    "title": {"type": "string"},
                    "note": {"type": "string"},
                    "due_at": {"type": "string"},
                    "remind_at": {"type": "string"},
                    "done": {"type": "boolean"},
                },
                "required": ["task_id"],
            },
            update_task,
            "正在修改日程…",
        ),
        "delete_task": Tool(
            "delete_task",
            "删除一条日程。task_id 先从 list_tasks 查得。",
            {
                "type": "object",
                "properties": {"task_id": {"type": "integer", "description": "日程 ID"}},
                "required": ["task_id"],
            },
            delete_task,
            "正在删除日程…",
        ),
        "create_reminder": Tool(
            "create_reminder",
            "设置提醒。remind_at 用 ISO 格式（如 2026-10-11T14:00）。",
            {
                "type": "object",
                "properties": {
                    "title": {"type": "string", "description": "提醒标题"},
                    "remind_at": {"type": "string", "description": "提醒时间"},
                    "body": {"type": "string", "description": "提醒正文"},
                    "channel": {
                        "type": "string",
                        "enum": ["both", "pc", "phone"],
                        "description": "提醒渠道",
                    },
                },
                "required": ["title", "remind_at"],
            },
            create_reminder,
            "正在设置提醒…",
        ),
        "get_weather": Tool(
            "get_weather",
            "查询城市天气，支持今天到未来一周。主人问天气时调用，并且必须把 day 一起传："
            "问某一天传 今天/明天/后天/大后天；问一周或这几天传「未来一周」，"
            "一次就能拿到 7 天，不要拆成多次调用。",
            {
                "type": "object",
                "properties": {
                    "city": {"type": "string", "description": "城市名，如 北京"},
                    "day": {
                        "type": "string",
                        "description": (
                            "必填。要查哪一天，照抄主人的说法：今天/明天/后天/大后天、"
                            "周三或星期日、11月2日或 2026-11-02、三天后；"
                            "主人问一周、这几天、未来几天时传「未来一周」，工具会一次返回 7 天逐日预报。"
                        ),
                    },
                },
                "required": ["city", "day"],
            },
            get_weather,
            "正在查天气…",
        ),
        "web_search": Tool(
            "web_search",
            "联网搜索。当主人问需要上网查的信息时调用。",
            {
                "type": "object",
                "properties": {"query": {"type": "string", "description": "搜索关键词"}},
                "required": ["query"],
            },
            web_search,
            "正在联网搜索…",
        ),
    }

    if habits is not None:
        tools.update(_habit_tools(habits))
    return tools


def _habit_tools(habits) -> dict[str, Tool]:
    """「记住 / 忘记习惯」两个工具；绑定到传入的 HabitStore。"""

    def remember_habit(text: str, **_args) -> str:
        ok, message = habits.add(text)
        return f"已记住：{message}" if ok else f"没记成：{message}"

    def forget_habit(keyword: str, **_args) -> str:
        removed = habits.forget(keyword)
        return f"忘掉了 {removed} 条相关习惯" if removed else "没找到匹配的习惯"

    return {
        "remember_habit": Tool(
            "remember_habit",
            "记住主人的长期偏好（作息、饮食、学习习惯等）。只记稳定偏好，一次性的临时安排不要记。",
            {
                "type": "object",
                "properties": {
                    "text": {"type": "string", "description": "一句话描述这条习惯，80 字以内"}
                },
                "required": ["text"],
            },
            remember_habit,
            "正在记下…",
        ),
        "forget_habit": Tool(
            "forget_habit",
            "忘掉与关键词相关的习惯。主人说「别再记着…」时调用。",
            {
                "type": "object",
                "properties": {"keyword": {"type": "string", "description": "要忘掉的关键词"}},
                "required": ["keyword"],
            },
            forget_habit,
            "正在忘掉…",
        ),
    }
