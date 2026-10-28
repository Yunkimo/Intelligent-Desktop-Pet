"""Agent 工具循环：让大模型通过 function calling 调用后端与联网工具。

流程：非流式请求探测 tool_calls → 执行工具 → 把结果作为 tool 消息喂回 →
重复（最多 max_rounds 轮）→ 最终流式回复。
"""

import json

from .tools import Tool, tool_schema

_MAX_ROUNDS = 3


class Agent:
    """编排工具调用。依赖 LLMClient 门面（chat_with_tools / chat）。"""

    def __init__(self, client, tools: dict[str, Tool], max_rounds: int = _MAX_ROUNDS) -> None:
        self.client = client
        self.tools = tools
        self.max_rounds = max_rounds

    def _schemas(self) -> list[dict]:
        return [tool_schema(t) for t in self.tools.values()]

    def run(self, messages: list[dict], on_chunk=None, on_status=None) -> str:
        """执行工具循环并返回最终文本回复。

        on_chunk(str) 流式增量回调；on_status(str) 工具执行时的状态回调。
        """
        msgs = [dict(m) for m in messages]
        used_tools = False
        for _ in range(self.max_rounds):
            reply = self.client.chat_with_tools(msgs, self._schemas())
            tool_calls = reply.get("tool_calls") or []
            if not tool_calls:
                # 全程未动工具：首轮拿到的就是最终答案，直接复用省一次流式请求
                if not used_tools:
                    content = reply.get("content") or ""
                    if on_chunk is not None:
                        on_chunk(content)
                    return content
                break
            used_tools = True
            msgs.append(
                {
                    "role": "assistant",
                    "content": reply.get("content") or "",
                    "tool_calls": tool_calls,
                }
            )
            for call in tool_calls:
                msgs.append(
                    {
                        "role": "tool",
                        "tool_call_id": call["id"],
                        "content": self._execute(call, on_status),
                    }
                )
        # 动过工具（或轮次耗尽）后，再做一次流式回复，让最终答案逐字出现
        return self.client.chat(msgs, on_chunk=on_chunk)

    def _execute(self, call: dict, on_status) -> str:
        name = call["function"]["name"]
        tool = self.tools.get(name)
        if tool is None:
            return f"未知工具：{name}"
        if on_status is not None:
            on_status(tool.status)
        try:
            args = json.loads(call["function"].get("arguments") or "{}")
        except json.JSONDecodeError:
            args = {}
        try:
            return tool.fn(**args)
        except Exception as exc:  # noqa: BLE001 - 工具异常反馈给模型，由其决定如何应对
            return f"工具执行失败：{exc}"
