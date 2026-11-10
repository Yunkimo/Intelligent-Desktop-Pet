"""语音输出开关测试：不构造 GUI，直接验证窗口方法的开关语义。"""

from types import SimpleNamespace

from pet.window import PetWindow


class _Settings:
    def __init__(self, enabled: bool = True) -> None:
        self.enable_voice = enabled
        self.persisted: list[bool] = []

    def update_voice_enabled(self, enabled: bool) -> None:
        self.enable_voice = bool(enabled)
        self.persisted.append(bool(enabled))


def _fake(enabled: bool, calls: list[str]) -> SimpleNamespace:
    return SimpleNamespace(
        settings=_Settings(enabled),
        bubble=SimpleNamespace(set_text=calls.append),
        _stop_voice=lambda: calls.append("stop"),
    )


def test_toggle_voice_off_stops_playback_and_persists():
    calls: list[str] = []
    window = _fake(True, calls)

    PetWindow._toggle_voice(window)

    assert window.settings.enable_voice is False
    assert window.settings.persisted == [False]
    assert calls == ["stop", "语音输出已关闭"]


def test_toggle_voice_on_does_not_stop_playback():
    calls: list[str] = []
    window = _fake(False, calls)

    PetWindow._toggle_voice(window)

    assert window.settings.enable_voice is True
    assert window.settings.persisted == [True]
    assert calls == ["语音输出已开启"]


def test_speak_is_skipped_when_disabled():
    calls: list[str] = []

    class _Worker:
        def __init__(self, *_a, **_kw):
            calls.append("worker")

    window = SimpleNamespace(
        settings=_Settings(False),
        tts_engine=object(),
        tts_worker=None,
    )

    import pet.window as window_module

    original = window_module.TTSWorker
    window_module.TTSWorker = _Worker
    try:
        PetWindow._speak(window, "你好")
    finally:
        window_module.TTSWorker = original

    assert calls == []  # 关闭时根本不启动合成线程
    assert window.tts_worker is None


def test_play_voice_discards_file_when_disabled(tmp_path):
    path = tmp_path / "speech.mp3"
    path.write_bytes(b"audio")
    window = SimpleNamespace(settings=_Settings(False))

    PetWindow._play_voice(window, str(path))

    assert not path.exists()
