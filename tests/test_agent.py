"""Agent 工具循环测试：用假客户端隔离 LLM，验证工具执行与最终回复。"""

import json

from pet.agent import Agent
from pet.tools import Tool


class _FakeClient:
    def __init__(self, replies, final="最终回复", final_chunks=None) -> None:
        self.replies = list(replies)  # chat_with_tools 依次弹出
        self.final = final
        self.final_chunks = final_chunks or ["最", "终", "回", "复"]
        self.chat_calls = 0
        self.chat_with_tools_calls = 0

    def chat_with_tools(self, messages, tools, on_chunk=None):
        self.chat_with_tools_calls += 1
        return self.replies.pop(0)

    def chat(self, messages, on_chunk=None):
        self.chat_calls += 1
        for c in self.final_chunks:
            if on_chunk is not None:
                on_chunk(c)
        return self.final


def _tc(tool_id: str, name: str, args: dict) -> dict:
    return {"id": tool_id, "function": {"name": name, "arguments": json.dumps(args)}}


def test_no_tool_reuses_first_reply():
    client = _FakeClient([{"content": "直接答", "tool_calls": []}])
    chunks: list[str] = []
    result = Agent(client, {}).run([{"role": "user", "content": "hi"}], on_chunk=chunks.append)
    assert result == "直接答"
    assert chunks == ["直接答"]
    assert client.chat_calls == 0  # 未动工具，不再二次流式请求


def test_tool_loop_executes_and_streams_final():
    executed: dict = {}

    def create_task(title, **_a):
        executed["title"] = title
        return f"已新增「{title}」"

    tools = {
        "create_task": Tool(
            "create_task",
            "新增日程",
            {"type": "object", "properties": {}},
            create_task,
            "正在安排…",
        )
    }
    client = _FakeClient(
        [
            {"content": "", "tool_calls": [_tc("1", "create_task", {"title": "复习"})]},
            {"content": "", "tool_calls": []},
        ]
    )
    statuses: list[str] = []
    chunks: list[str] = []
    result = Agent(client, tools).run(
        [{"role": "user", "content": "帮我加日程"}],
        on_chunk=chunks.append,
        on_status=statuses.append,
    )

    assert executed == {"title": "复习"}
    assert statuses == ["正在安排…"]
    assert result == "最终回复"
    assert chunks == ["最", "终", "回", "复"]
    assert client.chat_calls == 1  # 动过工具 → 最终流式一次


def test_unknown_tool_fed_back_as_result():
    client = _FakeClient(
        [
            {"content": "", "tool_calls": [_tc("1", "nope", {})]},
            {"content": "", "tool_calls": []},
        ]
    )
    agent = Agent(client, {})
    agent.run([{"role": "user", "content": "x"}])
    assert client.chat_with_tools_calls == 2  # 未知工具当作结果喂回，进入第二轮


# ---------- 未调用工具时的强制重试 ----------
class _ScriptedClient:
    """按顺序返回预设回复，并记录每次调用是否带 force。"""

    def __init__(self, replies):
        self._replies = list(replies)
        self.forces: list[bool] = []

    def chat_with_tools(self, messages, tools, on_chunk=None, force=False):
        self.forces.append(force)
        return self._replies.pop(0)

    def chat(self, messages, on_chunk=None):
        return "最终回复"


def _tool(name="get_weather"):
    from pet.tools import Tool

    return Tool(
        name, "测试工具", {"type": "object", "properties": {}}, lambda **_: "工具结果", "正在查…"
    )


def test_forced_retry_when_model_gives_up_without_calling_tool():
    from pet.agent import Agent

    client = _ScriptedClient(
        [
            {"content": "我这边查不到天气预报呢", "tool_calls": []},
            {
                "content": "",
                "tool_calls": [
                    {
                        "id": "t1",
                        "type": "function",
                        "function": {"name": "get_weather", "arguments": "{}"},
                    }
                ],
            },
            {"content": "查到了", "tool_calls": []},
        ]
    )
    agent = Agent(client, {"get_weather": _tool()})

    agent.run([{"role": "user", "content": "北京明天天气怎么样"}])

    assert client.forces == [False, True, False]  # 第二次被强制调用


def test_no_forced_retry_for_ordinary_chat():
    from pet.agent import Agent

    client = _ScriptedClient([{"content": "哈哈，我不太懂呢", "tool_calls": []}])
    agent = Agent(client, {"get_weather": _tool()})

    agent.run([{"role": "user", "content": "讲个笑话"}])

    assert client.forces == [False]


def test_no_forced_retry_when_reply_is_not_giving_up():
    from pet.agent import Agent

    client = _ScriptedClient([{"content": "今天适合出门走走", "tool_calls": []}])
    agent = Agent(client, {"get_weather": _tool()})

    agent.run([{"role": "user", "content": "今天天气真好"}])

    assert client.forces == [False]  # 没调工具但也没说查不到，不强制
