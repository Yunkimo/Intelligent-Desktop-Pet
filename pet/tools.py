"""工具注册表：把后端 REST 与联网能力封装成大模型可调用的 function。

每个工具 = JSON schema（供 function calling）+ callable（执行并返回一句话结果）。
callable 通过闭包绑定到 BackendClient，便于用假后端做单元测试。
"""

from dataclasses import dataclass
from typing import Callable
from urllib.parse import quote

import httpx

from .backend_client import BackendClient
from .timeparse import normalize_datetime

# 联网工具超时：避免工具循环长时间挂起
_WEATHER_TIMEOUT_SECS = 8.0


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


def build_tools(backend: BackendClient) -> dict[str, Tool]:
    """构造工具注册表，所有 callable 绑定到给定 backend。"""

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

    def get_weather(city: str, **_args) -> str:
        try:
            resp = httpx.get(
                f"https://wttr.in/{quote(city)}",
                params={"format": "%l：%c %t，体感 %f"},
                headers={"Accept-Language": "zh"},
                timeout=_WEATHER_TIMEOUT_SECS,
            )
            resp.raise_for_status()
        except httpx.HTTPError as exc:
            return f"查天气失败：{exc}"
        return resp.text.strip()

    def web_search(query: str, **_args) -> str:
        from ddgs import DDGS  # 延迟导入：无网/未装时不影响其它工具

        try:
            results = DDGS().text(query, max_results=5)
        except Exception as exc:  # noqa: BLE001 - 无网/被限流时给出可读反馈而非挂起
            return f"搜索「{query}」失败：{exc}"
        if not results:
            return f"没有搜到与「{query}」相关的结果"
        return "\n".join(f"- {r.get('title', '')}：{r.get('href', '')}" for r in results)

    return {
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
            "查询某城市实时天气。当主人问天气时调用。",
            {
                "type": "object",
                "properties": {"city": {"type": "string", "description": "城市名，如 北京"}},
                "required": ["city"],
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
