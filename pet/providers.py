"""LLM 提供者抽象：策略模式（Strategy）+ 工厂方法（Factory Method）。

把「调用哪家 LLM」抽象成策略，便于在不改上层代码的前提下切换
DeepSeek / 通义 / 智谱 / Moonshot 等任意 OpenAI 兼容服务。
"""

from abc import ABC, abstractmethod
from typing import Callable
from urllib.parse import urlsplit

from openai import BadRequestError, OpenAI

from .config import Settings

# 服务商拒绝 stream_options 时抛出的内部信号，用于降级重试且不重复计费
_STREAM_USAGE_UNSUPPORTED = (TypeError, BadRequestError)


class _UnsupportedStreamOptions(Exception):
    """当前服务商不接受 stream_options；仍需重新请求不带该参数的版本。"""


class ChatProvider(ABC):
    """LLM 对话提供者接口（策略）。"""

    @abstractmethod
    def stream_chat(self, messages: list[dict], on_chunk=None) -> str:
        """流式对话。on_chunk(str) 每收到一个增量被调用；返回完整文本。"""

    @abstractmethod
    def chat_with_tools(
        self, messages: list[dict], tools: list[dict], on_chunk=None, force: bool = False
    ) -> dict:
        """带工具的单次非流式调用。返回 {"content": str, "tool_calls": [...]}。

        force=True 时用 tool_choice="required" 强制模型必须调用工具，用于用户明确
        要求查实时信息、模型却直接作答的场景。on_chunk 仅为接口对齐保留。
        """


class OpenAICompatProvider(ChatProvider):
    """OpenAI 兼容协议实现（DeepSeek 等）。客户端惰性创建，避免未配密钥时启动即报错。"""

    def __init__(
        self,
        api_key: str,
        base_url: str,
        model: str,
        temperature: float = 0.9,
        max_tokens: int = 1024,
        on_usage: Callable[[object, str], None] | None = None,
    ) -> None:
        self.api_key = api_key
        self.base_url = base_url
        self.model = model
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.on_usage = on_usage
        # 服务商一旦拒绝过 stream_options 就不再尝试，避免每次对话都多打一次请求
        self._stream_usage_supported = True
        self._client: OpenAI | None = None

    def _get_client(self) -> OpenAI:
        if self._client is None:
            self._client = OpenAI(api_key=self.api_key, base_url=self.base_url)
        return self._client

    def _chat_options(self) -> dict:
        """新版 DeepSeek 默认思考；桌宠采用普通对话，避免工具续轮丢失推理字段。"""
        if urlsplit(self.base_url).hostname == "api.deepseek.com" and self.model in {
            "deepseek-flash",
            "deepseek-v4-pro",
            "deepseek-v4-flash",
            "deepseek-v4-flash-vision-exp",
        }:
            return {"extra_body": {"thinking": {"type": "disabled"}}}
        return {}

    def _report_usage(self, usage: object) -> None:
        """把 usage 交给调用方记账；记账失败绝不能影响对话本身。"""
        if usage is None or self.on_usage is None:
            return
        try:
            self.on_usage(usage, self.model)
        except Exception:  # noqa: BLE001 - 统计是旁路，异常一律吞掉
            pass

    def stream_chat(self, messages: list[dict], on_chunk=None) -> str:
        if self._stream_usage_supported:
            try:
                return self._stream_once(messages, on_chunk, include_usage=True)
            except _UnsupportedStreamOptions:
                self._stream_usage_supported = False
        return self._stream_once(messages, on_chunk, include_usage=False)

    def _stream_once(self, messages: list[dict], on_chunk, include_usage: bool) -> str:
        """单次流式请求；include_usage 时额外请求用量统计。

        usage 出现在最后一个 chunk 上，且该 chunk 的 choices 未必为空，因此必须在
        判断 choices 之前读取。只在还没收到任何一帧时降级重试，避免重复计费。
        """
        extra = {"stream_options": {"include_usage": True}} if include_usage else {}
        parts: list[str] = []
        received = False
        try:
            stream = self._get_client().chat.completions.create(
                model=self.model,
                messages=messages,
                stream=True,
                temperature=self.temperature,
                max_tokens=self.max_tokens,
                **self._chat_options(),
                **extra,
            )
            for chunk in stream:
                received = True
                self._report_usage(getattr(chunk, "usage", None))
                if not chunk.choices:
                    continue
                content = getattr(chunk.choices[0].delta, "content", None)
                if content:
                    parts.append(content)
                    if on_chunk is not None:
                        on_chunk(content)
        except _STREAM_USAGE_UNSUPPORTED as exc:
            if include_usage and not received:
                raise _UnsupportedStreamOptions from exc
            raise
        return "".join(parts)

    def chat_with_tools(
        self, messages: list[dict], tools: list[dict], on_chunk=None, force: bool = False
    ) -> dict:
        resp = self._get_client().chat.completions.create(
            model=self.model,
            messages=messages,
            tools=tools,
            tool_choice="required" if force else "auto",
            temperature=self.temperature,
            max_tokens=self.max_tokens,
            **self._chat_options(),
        )
        self._report_usage(getattr(resp, "usage", None))
        msg = resp.choices[0].message
        tool_calls = [
            {
                "id": tc.id,
                "type": tc.type,  # DeepSeek 反序列化要求 tool_call 带 type 字段，缺了会 422
                "function": {"name": tc.function.name, "arguments": tc.function.arguments},
            }
            for tc in (msg.tool_calls or [])
        ]
        return {"content": msg.content or "", "tool_calls": tool_calls}


def create_chat_provider(
    settings: Settings, on_usage: Callable[[object, str], None] | None = None
) -> ChatProvider:
    """工厂方法：根据配置创建对话提供者；on_usage 用于旁路记录 token 用量。"""
    return OpenAICompatProvider(
        settings.llm_api_key,
        settings.llm_base_url,
        settings.llm_model,
        temperature=settings.llm_temperature,
        max_tokens=settings.llm_max_tokens,
        on_usage=on_usage,
    )
