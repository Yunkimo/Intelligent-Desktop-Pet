"""录音设备回退与静默自动结束。"""

import numpy as np
import pytest

from pet import worker


class _FakeStream:
    def __init__(self, **kwargs):
        self.kwargs = kwargs


class _Engine:
    samplerate = 16000


def _callback(*_args):
    pass


def test_open_stream_refreshes_devices_then_retries(monkeypatch):
    calls = []
    refreshed = []

    def fake_stream(**kwargs):
        calls.append(kwargs)
        if len(calls) == 1:
            raise RuntimeError("Error querying device -1")
        return _FakeStream(**kwargs)

    monkeypatch.setattr(worker.sd, "InputStream", fake_stream)
    monkeypatch.setattr(worker, "_refresh_audio_devices", lambda: refreshed.append(True))

    stream = worker.ASRWorker(_Engine())._open_stream(_callback)

    assert refreshed == [True]
    assert stream.kwargs["samplerate"] == 16000
    assert "device" not in stream.kwargs


def test_open_stream_falls_back_to_first_input_device(monkeypatch):
    devices = [{"max_input_channels": 0}, {"max_input_channels": 2}]

    def fake_stream(**kwargs):
        if "device" not in kwargs:
            raise RuntimeError("Error querying device -1")
        return _FakeStream(**kwargs)

    monkeypatch.setattr(worker.sd, "InputStream", fake_stream)
    monkeypatch.setattr(worker, "_refresh_audio_devices", lambda: None)
    monkeypatch.setattr(worker.sd, "query_devices", lambda: devices)

    stream = worker.ASRWorker(_Engine())._open_stream(_callback)

    assert stream.kwargs["device"] == 1


def test_open_stream_reports_missing_microphone(monkeypatch):
    def fake_stream(**_kwargs):
        raise RuntimeError("Error querying device -1")

    monkeypatch.setattr(worker.sd, "InputStream", fake_stream)
    monkeypatch.setattr(worker, "_refresh_audio_devices", lambda: None)
    monkeypatch.setattr(worker.sd, "query_devices", lambda: [{"max_input_channels": 0}])

    with pytest.raises(RuntimeError, match="没有可用的麦克风"):
        worker.ASRWorker(_Engine())._open_stream(_callback)


def test_silence_gate_ignores_speech_and_counts_silence():
    gate = worker._SilenceGate(samplerate=1000, silence_secs=1, threshold=0.01)
    silent = np.zeros(400, dtype=np.float32)
    speech = np.full(400, 0.5, dtype=np.float32)

    assert gate.feed(silent) is False
    assert gate.feed(speech) is False  # 检测到说话，静默计数清零
    assert gate.feed(silent) is False
    assert gate.feed(silent) is False  # 800 < 1000
    assert gate.feed(silent) is True  # 1200 >= 1000


def test_run_stops_on_silence_and_emits_text(monkeypatch):
    captured = []
    sizes = []

    class _QuietEngine:
        samplerate = 16000

        def transcribe(self, audio):
            sizes.append(audio.size)
            return "你好"

    monkeypatch.setattr(worker, "_refresh_audio_devices", lambda: None)
    silence = np.zeros((8000, 1), dtype=np.float32)

    class _FakeStream:
        def __init__(self, callback):
            self.callback = callback

        def __enter__(self):
            # 两块 0.5 秒静音，正好凑满 1 秒，触发自动结束
            self.callback(silence, silence.shape[0], None, None)
            self.callback(silence, silence.shape[0], None, None)
            return self

        def __exit__(self, *args):
            return False

    asr = worker.ASRWorker(_QuietEngine(), max_duration=60, silence_secs=1)
    monkeypatch.setattr(asr, "_open_stream", lambda callback: _FakeStream(callback))
    asr.text.connect(captured.append)

    asr.run()

    assert captured == ["你好"]
    assert sizes == [16000]
