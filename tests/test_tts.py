"""语音请求失败和超时不遗留临时音频。"""

import asyncio
from pathlib import Path

import pytest

from pet.tts import TTSEngine


@pytest.mark.parametrize("mode", ["success", "failure", "timeout"])
def test_synthesis_lifecycle(tmp_path, monkeypatch, mode):
    import pet.tts as tts

    original = tts.tempfile.NamedTemporaryFile
    monkeypatch.setattr(
        tts.tempfile, "NamedTemporaryFile", lambda **kw: original(dir=tmp_path, **kw)
    )

    class Communicate:
        def __init__(self, *args, **kwargs):
            pass

        async def save(self, path):
            Path(path).write_bytes(b"partial audio")
            if mode == "failure":
                raise RuntimeError("upstream failure")
            if mode == "timeout":
                await asyncio.Event().wait()

    monkeypatch.setattr(tts.edge_tts, "Communicate", Communicate)
    engine = TTSEngine(timeout=0.02, windows_fallback=False)
    if mode == "success":
        result = Path(engine.synthesize("test"))
        assert result.read_bytes() == b"partial audio"
    else:
        with pytest.raises(RuntimeError if mode == "failure" else asyncio.TimeoutError):
            engine.synthesize("test")
        assert list(tmp_path.glob("*.mp3")) == []


@pytest.mark.parametrize("failure", [False, True])
def test_windows_fallback_passes_text_as_data_and_cleans_failure(tmp_path, monkeypatch, failure):
    import json
    import subprocess

    import pet.tts as tts

    original = tts.tempfile.NamedTemporaryFile
    monkeypatch.setattr(
        tts.tempfile, "NamedTemporaryFile", lambda **kw: original(dir=tmp_path, **kw)
    )
    text = "中文提醒 $(); `test`; 'quoted'"

    def run(command, **kwargs):
        assert text not in " ".join(command)
        data = json.loads(kwargs["input"])
        assert data["text"] == text
        assert kwargs["timeout"] == 30
        if failure:
            raise subprocess.TimeoutExpired(command, 30)
        Path(data["path"]).write_bytes(b"RIFF" + b"audio" * 20)

    monkeypatch.setattr(tts.subprocess, "run", run)
    if failure:
        with pytest.raises(subprocess.TimeoutExpired):
            TTSEngine()._synthesize_windows(text)
        assert list(tmp_path.glob("*.wav")) == []
    else:
        assert Path(TTSEngine()._synthesize_windows(text)).stat().st_size > 44


def test_online_failure_uses_configured_windows_fallback(tmp_path, monkeypatch):
    import pet.tts as tts

    original = tts.tempfile.NamedTemporaryFile
    monkeypatch.setattr(
        tts.tempfile, "NamedTemporaryFile", lambda **kw: original(dir=tmp_path, **kw)
    )
    monkeypatch.setattr(tts.sys, "platform", "win32")

    class Broken:
        def __init__(self, *args, **kwargs):
            pass

        async def save(self, path):
            raise RuntimeError("offline")

    monkeypatch.setattr(tts.edge_tts, "Communicate", Broken)
    calls = []
    engine = TTSEngine()
    monkeypatch.setattr(
        engine, "_synthesize_windows", lambda text: calls.append(text) or "local.wav"
    )
    assert engine.synthesize("hello") == "local.wav"
    assert calls == ["hello"]
    assert list(tmp_path.glob("*.mp3")) == []


# ---------- 朗读文本清洗 ----------
def test_sanitize_strips_emoji_but_keeps_words():
    from pet.tts import sanitize_for_speech

    assert sanitize_for_speech("今天天气晴 ☀️ 气温 11°C ✨") == "今天天气晴 气温 11°C"
    assert sanitize_for_speech("出门记得带伞 ☔") == "出门记得带伞"


def test_sanitize_strips_markdown_markers():
    from pet.tts import sanitize_for_speech

    assert sanitize_for_speech("**重点**：记得`喝水`") == "重点：记得喝水"
    assert sanitize_for_speech("- 第一项\n- 第二项") == "第一项\n第二项"
    assert sanitize_for_speech("## 小标题") == "小标题"


def test_sanitize_collapses_whitespace():
    from pet.tts import sanitize_for_speech

    assert sanitize_for_speech("  好多    空格  ") == "好多 空格"


def test_sanitize_returns_empty_for_emoji_only():
    from pet.tts import sanitize_for_speech

    assert sanitize_for_speech("🎉🎉✨") == ""


def test_synthesize_rejects_emoji_only_text():
    from pet.tts import TTSEngine

    engine = TTSEngine("zh-CN-XiaoxiaoNeural")
    try:
        engine.synthesize("🎉✨")
    except ValueError as exc:
        assert "没有可朗读" in str(exc)
    else:
        raise AssertionError("纯表情应当拒绝合成")


def test_sanitize_flattens_markdown_table():
    from pet.tts import sanitize_for_speech

    text = (
        "北京未来一周：\n"
        "| 日期 | 天气 | 气温 |\n"
        "|------|------|------|\n"
        "| 10/30 周五 | 晴 | 6.6~19.5°C |\n"
        "| 10/31 周六 | 阴 | 3.8~10.6°C |"
    )
    spoken = sanitize_for_speech(text)
    assert "|" not in spoken
    assert "---" not in spoken
    assert "10/30 周五，晴，6.6~19.5°C" in spoken
    assert "10/31 周六，阴，3.8~10.6°C" in spoken


def test_sanitize_strips_numbered_list_markers():
    from pet.tts import sanitize_for_speech

    assert sanitize_for_speech("1. 带伞\n2. 穿外套") == "带伞\n穿外套"
