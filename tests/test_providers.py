"""提供者（策略）与 LLM 客户端（门面）测试，使用 mock 隔离网络。"""

import pytest

from pet.llm import LLMClient, LLMError
from pet.providers import OpenAICompatProvider, create_chat_provider


class _Delta:
    def __init__(self, content):
        self.content = content


class _Choice:
    def __init__(self, content):
        self.delta = _Delta(content)


class _Chunk:
    def __init__(self, content):
        self.choices = [_Choice(content)] if content is not None else []


class _Completions:
    def __init__(self, chunks):
        self._chunks = chunks

    def create(self, **kwargs):
        return iter(self._chunks)


class _FakeClient:
    def __init__(self, chunks):
        self.chat = type("Chat", (), {"completions": _Completions(chunks)})()


@pytest.mark.parametrize("with_tools", [False, True])
@pytest.mark.parametrize(
    ("base_url", "model", "disable_thinking"),
    [
        ("https://api.deepseek.com", "deepseek-flash", True),
        ("https://api.deepseek.com/v1", "deepseek-v4-pro", True),
        ("https://example.test/v1", "deepseek-flash", False),
        ("https://api.deepseek.com", "deepseek-chat", False),
    ],
)
def test_modern_deepseek_uses_plain_chat_for_both_request_paths(
    monkeypatch, with_tools, base_url, model, disable_thinking
):
    """真实请求路径均带普通模式；其他兼容服务/旧模型不受影响。"""
    captured = {}

    class Completions:
        def create(self, **kwargs):
            captured.update(kwargs)
            if with_tools:
                return _RespMsg(_Msg("已收到", []))
            return iter([_Chunk("已收到")])

    provider = OpenAICompatProvider("test-key", base_url, model)
    client = type("Client", (), {"chat": type("Chat", (), {"completions": Completions()})()})()
    monkeypatch.setattr(provider, "_client", client)
    messages = [{"role": "user", "content": "你好"}]
    if with_tools:
        assert provider.chat_with_tools(messages, []) == {"content": "已收到", "tool_calls": []}
    else:
        assert provider.stream_chat(messages) == "已收到"
    if disable_thinking:
        assert captured["extra_body"] == {"thinking": {"type": "disabled"}}
    else:
        assert "extra_body" not in captured


def test_stream_chat_concatenates_and_callbacks(monkeypatch):
    provider = OpenAICompatProvider("sk", "https://x", "m")
    chunks = [_Chunk("你"), _Chunk(None), _Chunk("好")]
    monkeypatch.setattr(provider, "_client", _FakeClient(chunks))

    collected = []
    result = provider.stream_chat([{"role": "user", "content": "hi"}], on_chunk=collected.append)

    assert result == "你好"
    assert collected == ["你", "好"]


def test_llm_client_wraps_error():
    class _Boom:
        def stream_chat(self, messages, on_chunk=None):
            raise RuntimeError("boom")

    client = LLMClient(_Boom())
    with pytest.raises(LLMError):
        client.chat([{"role": "user", "content": "hi"}])


def test_factory_returns_openai_compat_provider():
    from pet.config import Settings

    provider = create_chat_provider(Settings())
    assert isinstance(provider, OpenAICompatProvider)


class _TCFunction:
    def __init__(self, name, arguments):
        self.name = name
        self.arguments = arguments


class _ToolCall:
    def __init__(self, tool_id, name, arguments):
        self.id = tool_id
        self.type = "function"
        self.function = _TCFunction(name, arguments)


class _Msg:
    def __init__(self, content, tool_calls):
        self.content = content
        self.tool_calls = tool_calls


class _ChoiceMsg:
    def __init__(self, msg):
        self.message = msg


class _RespMsg:
    def __init__(self, msg):
        self.choices = [_ChoiceMsg(msg)]


class _CompletionsMsg:
    def __init__(self, resp):
        self._resp = resp

    def create(self, **kwargs):
        return self._resp


class _FakeClientMsg:
    def __init__(self, resp):
        self.chat = type("Chat", (), {"completions": _CompletionsMsg(resp)})()


def test_chat_with_tools_parses_tool_calls(monkeypatch):
    provider = OpenAICompatProvider("sk", "https://x", "m")
    msg = _Msg("", [_ToolCall("t1", "get_weather", '{"city":"北京"}')])
    monkeypatch.setattr(provider, "_client", _FakeClientMsg(_RespMsg(msg)))

    out = provider.chat_with_tools(
        [{"role": "user", "content": "天气"}],
        [{"type": "function", "function": {"name": "get_weather"}}],
    )

    assert out["content"] == ""
    assert out["tool_calls"] == [
        {
            "id": "t1",
            "type": "function",
            "function": {"name": "get_weather", "arguments": '{"city":"北京"}'},
        }
    ]


def test_provider_stores_temperature_and_max_tokens():
    p = OpenAICompatProvider("sk", "https://x", "m", temperature=0.5, max_tokens=256)
    assert p.temperature == 0.5
    assert p.max_tokens == 256


def test_stream_chat_passes_generation_params(monkeypatch):
    captured: dict = {}

    class _CapturingCompletions:
        def create(self, **kwargs):
            captured.update(kwargs)
            return iter([])

    class _Client:
        chat = type("Chat", (), {"completions": _CapturingCompletions()})()

    provider = OpenAICompatProvider("sk", "https://x", "m", temperature=0.3, max_tokens=128)
    monkeypatch.setattr(provider, "_client", _Client)
    provider.stream_chat([{"role": "user", "content": "hi"}])
    assert captured["temperature"] == 0.3
    assert captured["max_tokens"] == 128


def test_chat_with_tools_multiple_tool_calls(monkeypatch):
    provider = OpenAICompatProvider("sk", "https://x", "m")
    msg = _Msg(
        "",
        [
            _ToolCall("t1", "get_weather", '{"city":"北京"}'),
            _ToolCall("t2", "list_tasks", "{}"),
        ],
    )
    monkeypatch.setattr(provider, "_client", _FakeClientMsg(_RespMsg(msg)))
    out = provider.chat_with_tools([{"role": "user", "content": "天气和日程"}], [])
    assert [tc["id"] for tc in out["tool_calls"]] == ["t1", "t2"]
    assert out["tool_calls"][1]["function"]["name"] == "list_tasks"


def test_chat_with_tools_empty_tool_calls(monkeypatch):
    provider = OpenAICompatProvider("sk", "https://x", "m")
    monkeypatch.setattr(provider, "_client", _FakeClientMsg(_RespMsg(_Msg("答", []))))
    out = provider.chat_with_tools([{"role": "user", "content": "x"}], [])
    assert out == {"content": "答", "tool_calls": []}


def test_llm_client_chat_with_tools_passthrough():
    class _Prov:
        def chat_with_tools(self, messages, tools, on_chunk=None):
            return {"content": "ok", "tool_calls": []}

    out = LLMClient(_Prov()).chat_with_tools([{"role": "user", "content": "hi"}], [])
    assert out == {"content": "ok", "tool_calls": []}


def test_llm_client_chat_with_tools_wraps_error():
    class _Boom:
        def chat_with_tools(self, messages, tools, on_chunk=None):
            raise RuntimeError("boom")

    with pytest.raises(LLMError):
        LLMClient(_Boom()).chat_with_tools([{"role": "user", "content": "hi"}], [])


# ---------- usage 采集 ----------
class _Usage:
    """最小 usage 伪对象，字段按需缺省。"""

    def __init__(self, prompt=10, completion=5, hit=None):
        self.prompt_tokens = prompt
        self.completion_tokens = completion
        if hit is not None:
            self.prompt_cache_hit_tokens = hit


class _UsageChunk:
    """可带 usage 的流式帧：usage 可能挂在 choices 非空的最后一帧上。"""

    def __init__(self, content=None, usage=None, with_choice=True):
        self.choices = [_Choice(content)] if with_choice else []
        self.usage = usage


def _provider_with_chunks(monkeypatch, chunks, sink):
    provider = OpenAICompatProvider("sk", "https://x", "deepseek-chat", on_usage=sink)
    monkeypatch.setattr(provider, "_client", _FakeClient(chunks))
    return provider


def test_stream_chat_reports_usage_attached_to_content_chunk(monkeypatch):
    """DeepSeek 把 usage 放在 choices 长度 1、delta 为空的最后一帧上。"""
    seen = []
    chunks = [_Chunk("你"), _UsageChunk(None, _Usage(10, 5, hit=3))]
    provider = _provider_with_chunks(monkeypatch, chunks, lambda u, m: seen.append((u, m)))

    result = provider.stream_chat([{"role": "user", "content": "hi"}])

    assert result == "你"
    assert len(seen) == 1
    assert seen[0][1] == "deepseek-chat"
    assert seen[0][0].prompt_tokens == 10


def test_stream_chat_reports_usage_on_empty_choices_chunk(monkeypatch):
    """标准 OpenAI 把 usage 放在 choices 为空的独立末帧，同样要能采集。"""
    seen = []
    chunks = [_UsageChunk("你"), _UsageChunk(None, _Usage(7, 2), with_choice=False)]
    provider = _provider_with_chunks(monkeypatch, chunks, lambda u, m: seen.append(u))

    assert provider.stream_chat([{"role": "user", "content": "hi"}]) == "你"
    assert len(seen) == 1


def test_stream_chat_without_usage_still_returns_text(monkeypatch):
    seen = []
    provider = _provider_with_chunks(monkeypatch, [_Chunk("好")], lambda u, m: seen.append(u))

    assert provider.stream_chat([{"role": "user", "content": "hi"}]) == "好"
    assert seen == []


def test_stream_chat_requests_usage_by_default(monkeypatch):
    captured = {}

    class _CapturingCompletions:
        def create(self, **kwargs):
            captured.update(kwargs)
            return iter([])

    class _Client:
        chat = type("Chat", (), {"completions": _CapturingCompletions()})()

    provider = OpenAICompatProvider("sk", "https://x", "m")
    monkeypatch.setattr(provider, "_client", _Client)
    provider.stream_chat([{"role": "user", "content": "hi"}])
    assert captured["stream_options"] == {"include_usage": True}


def test_stream_chat_falls_back_when_stream_options_rejected(monkeypatch):
    """服务商不认 stream_options 时退化为普通流式，且后续请求不再重复尝试。"""
    calls = []

    class _Completions:
        def create(self, **kwargs):
            calls.append(kwargs)
            if "stream_options" in kwargs:
                raise TypeError("unexpected keyword argument 'stream_options'")
            return iter([_Chunk("好")])

    class _Client:
        chat = type("Chat", (), {"completions": _Completions()})()

    provider = OpenAICompatProvider("sk", "https://x", "m")
    monkeypatch.setattr(provider, "_client", _Client)

    assert provider.stream_chat([{"role": "user", "content": "hi"}]) == "好"
    assert len(calls) == 2
    assert provider._stream_usage_supported is False

    assert provider.stream_chat([{"role": "user", "content": "again"}]) == "好"
    assert len(calls) == 3  # 第二次对话只发一次请求


def test_stream_chat_does_not_retry_after_it_started_streaming(monkeypatch):
    """已经收到内容后出错不再重试，避免同一轮对话被重复计费。"""
    calls = []

    class _Completions:
        def create(self, **kwargs):
            calls.append(kwargs)

            def generator():
                yield _Chunk("半")
                raise TypeError("mid-stream failure")

            return generator()

    class _Client:
        chat = type("Chat", (), {"completions": _Completions()})()

    provider = OpenAICompatProvider("sk", "https://x", "m")
    monkeypatch.setattr(provider, "_client", _Client)

    with pytest.raises(TypeError):
        provider.stream_chat([{"role": "user", "content": "hi"}])
    assert len(calls) == 1


def test_chat_with_tools_reports_usage_and_keeps_return_shape(monkeypatch):
    seen = []
    resp = _RespMsg(_Msg("答", []))
    resp.usage = _Usage(20, 4, hit=8)
    provider = OpenAICompatProvider("sk", "https://x", "m", on_usage=lambda u, m: seen.append(u))
    monkeypatch.setattr(provider, "_client", _FakeClientMsg(resp))

    out = provider.chat_with_tools([{"role": "user", "content": "hi"}], [])

    assert set(out) == {"content", "tool_calls"}  # 返回结构不能因统计而改变
    assert len(seen) == 1 and seen[0].prompt_tokens == 20


def test_usage_sink_error_does_not_break_chat(monkeypatch):
    def boom(_usage, _model):
        raise RuntimeError("记账炸了")

    provider = _provider_with_chunks(monkeypatch, [_UsageChunk("好", _Usage())], boom)
    assert provider.stream_chat([{"role": "user", "content": "hi"}]) == "好"
