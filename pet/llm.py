"""LLM 客户端：对话门面（上下文），持有一个 ChatProvider 策略。纯 Python，不依赖 Qt。"""

from .providers import ChatProvider


class LLMError(Exception):
    """统一的 LLM 调用异常，便于 UI 提示。"""


class LLMClient:
    def __init__(self, provider: ChatProvider) -> None:
        self.provider = provider

    def chat(self, messages: list[dict], on_chunk=None) -> str:
        """流式对话。on_chunk(str) 每收到一个增量被调用；返回完整文本。"""
        try:
            return self.provider.stream_chat(messages, on_chunk=on_chunk)
        except LLMError:
            raise
        except Exception as exc:  # noqa: BLE001 - 统一包装为 LLMError
            raise LLMError(f"{exc}") from exc

    def chat_with_tools(self, messages: list[dict], tools: list[dict], on_chunk=None) -> dict:
        """带工具的单次非流式调用，返回 {"content": str, "tool_calls": [...]}。"""
        try:
            return self.provider.chat_with_tools(messages, tools, on_chunk=on_chunk)
        except LLMError:
            raise
        except Exception as exc:  # noqa: BLE001 - 统一包装为 LLMError
            raise LLMError(f"{exc}") from exc
