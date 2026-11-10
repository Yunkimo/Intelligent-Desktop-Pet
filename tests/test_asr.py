"""语音识别测试：归一化、模型加载与 transcribe 参数（VAD / 热词 / 上下文）。"""

import sys
import types

import numpy as np
import pytest

from pet.asr import ASREngine


def _install_fake_whisper(monkeypatch, model_cls):
    module = types.ModuleType("faster_whisper")
    module.WhisperModel = model_cls
    monkeypatch.setitem(sys.modules, "faster_whisper", module)


def test_load_model_prefers_local_cache(monkeypatch):
    calls = []

    class _Model:
        def __init__(self, *args, **kwargs):
            calls.append(kwargs)

    _install_fake_whisper(monkeypatch, _Model)

    engine = ASREngine("base")
    engine._load_model()

    assert calls == [{"device": "cpu", "compute_type": "int8", "local_files_only": True}]


def test_load_model_downloads_when_cache_missing(monkeypatch):
    calls = []

    class _Model:
        def __init__(self, *args, **kwargs):
            calls.append(kwargs)
            if kwargs.get("local_files_only"):
                raise RuntimeError("model not found")

    _install_fake_whisper(monkeypatch, _Model)

    engine = ASREngine("base")
    engine._load_model()

    assert calls[0]["local_files_only"] is True
    assert "local_files_only" not in calls[1]
    assert engine._model is not None


def test_normalize_scales_peak_to_target():
    audio = np.array([0.0, 0.5, -1.0, 0.25], dtype=np.float32)
    out = ASREngine._normalize(audio)
    assert float(np.max(np.abs(out))) == pytest.approx(0.9)
    assert out.dtype == np.float32


def test_normalize_keeps_silence_unchanged():
    audio = np.array([0.0, 0.00001], dtype=np.float32)
    out = ASREngine._normalize(audio)
    assert np.array_equal(out, audio)


def test_normalize_empty_audio():
    out = ASREngine._normalize(np.zeros(0, dtype=np.float32))
    assert out.size == 0


def test_transcribe_enables_vad_and_injects_hotwords(monkeypatch):
    class _Seg:
        def __init__(self, text):
            self.text = text

    captured = {}

    class _Model:
        def transcribe(self, audio, **kwargs):
            captured["kwargs"] = kwargs
            captured["audio"] = audio
            return ([_Seg("你好")], None)

    engine = ASREngine(hotwords="课表 日程")
    monkeypatch.setattr(engine, "_load_model", lambda: _Model())

    text = engine.transcribe(np.array([0.0, 0.5, -0.5], dtype=np.float32))

    assert text == "你好"
    assert captured["kwargs"]["vad_filter"] is True
    assert captured["kwargs"]["condition_on_previous_text"] is False
    assert captured["kwargs"]["initial_prompt"] == "课表 日程"
    assert float(np.max(np.abs(captured["audio"]))) == pytest.approx(0.9)


def test_transcribe_without_hotwords_uses_none_prompt(monkeypatch):
    class _Seg:
        text = "hi"

    captured = {}

    class _Model:
        def transcribe(self, audio, **kwargs):
            captured.update(kwargs)
            return ([_Seg()], None)

    engine = ASREngine()
    monkeypatch.setattr(engine, "_load_model", lambda: _Model())
    engine.transcribe(np.array([0.2], dtype=np.float32))

    assert captured["initial_prompt"] is None
