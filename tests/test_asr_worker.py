"""录音设备回退：默认输入设备失效（如蓝牙耳机断开）后仍能录音。"""

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
