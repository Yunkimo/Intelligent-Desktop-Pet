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
