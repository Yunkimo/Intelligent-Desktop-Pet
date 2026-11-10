"""语音校对请求和桌宠草稿确认的回归测试。"""

import json
import time

import httpx
import numpy as np
import pytest
from openai import OpenAI
from PyQt6.QtCore import Qt
from PyQt6.QtTest import QTest

from pet.config import Settings
from pet.providers import OpenAICompatProvider
from pet.window import PetWindow


@pytest.mark.parametrize(
    ("reply", "expected"),
    [
        ('{"text":"上午有什么课？"}', "上午有什么课？"),
        ('{"text":"", "action":"send"}', "商午有什么课"),
        ("invalid JSON", "商午有什么课"),
    ],
)
def test_correction_is_text_only_and_reports_usage(reply, expected):
    usage = []

    def respond(request):
        body = json.loads(request.content)
        assert "tools" not in body
        assert [m["role"] for m in body["messages"]] == ["system", "user"]
        assert json.loads(body["messages"][1]["content"]) == {"transcript": "商午有什么课"}
        assert body["thinking"] == {"type": "disabled"}
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"role": "assistant", "content": reply}}],
                "usage": {"prompt_tokens": 120, "completion_tokens": 10, "total_tokens": 130},
            },
        )

    provider = OpenAICompatProvider(
        "test", "https://api.deepseek.com", "deepseek-flash", on_usage=lambda *a: usage.append(a)
    )
    with OpenAI(
        api_key="test", http_client=httpx.Client(transport=httpx.MockTransport(respond))
    ) as sdk:
        provider._client = sdk
        assert provider.correct_transcript("商午有什么课") == expected
    assert len(usage) == 1
    assert usage[0][0].total_tokens == 130


@pytest.mark.parametrize(
    ("mode", "expected"),
    [("corrected", "上午有什么课？"), ("timeout", "商午有什么课"), ("no_key", "商午有什么课")],
)
def test_voice_correction_waits_for_confirmation(qapp, monkeypatch, tmp_path, mode, expected):
    class FakeStream:
        def __init__(self, *, callback, **kwargs):
            self.callback = callback

        def __enter__(self):
            self.callback(np.ones((1600, 1), dtype=np.float32), 1600, None, None)
            return self

        def __exit__(self, *args):
            pass

    sent = []
    corrections = []

    def correct(text):
        corrections.append(text)
        if mode == "timeout":
            raise httpx.ReadTimeout("simulated timeout")
        return "上午有什么课？"

    settings = Settings()
    settings.llm_api_key = "" if mode == "no_key" else "test"
    settings.api_token = ""
    settings.asr_ai_correction = True
    settings.health_enabled = False
    settings.tray_enabled = False
    settings.weather_tip_enabled = False
    settings.habits_enabled = False
    settings.monitor_claude = False
    settings.monitor_codex = False
    settings.persist_history = False
    settings.history_path = tmp_path / "history.json"
    settings.usage_path = tmp_path / "usage.json"

    monkeypatch.setattr("pet.window.AccountStore.load", lambda self: None)
    monkeypatch.setattr("pet.worker.sd.InputStream", FakeStream)
    monkeypatch.setattr(PetWindow, "_init_hotkey", lambda self: setattr(self, "hotkey", None))
    monkeypatch.setattr(PetWindow, "send_text", lambda self, text: sent.append(text))
    window = PetWindow(settings)
    try:
        monkeypatch.setattr(window.asr_engine, "transcribe", lambda audio: "商午有什么课")
        monkeypatch.setattr(window.llm.provider, "correct_transcript", correct)
        window.show()
        window._on_hotkey_pressed()
        window._on_hotkey_released()
        deadline = time.monotonic() + 4
        while window.asr_worker is not None and time.monotonic() < deadline:
            qapp.processEvents()
            time.sleep(0.01)
        assert window.asr_worker is None
        assert window.input.isVisible()
        assert window.input.edit.text() == expected
        assert window.input.mic.isEnabled()
        assert corrections == ([] if mode == "no_key" else ["商午有什么课"])
        assert not sent
        QTest.keyClick(window.input.edit, Qt.Key.Key_Return)
        assert sent == [expected]
    finally:
        window.close()
