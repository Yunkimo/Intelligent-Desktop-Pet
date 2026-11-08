"""Agent 状态音效：使用本地素材覆盖，默认从源码生成两个短提示音。"""

import math
import struct
import wave
from pathlib import Path
from tempfile import TemporaryDirectory

from PyQt6.QtCore import QObject, QUrl
from PyQt6.QtMultimedia import QSoundEffect

CUE_FILES = {
    "waiting": "assets_Pending confirmation.wav",
    "done": "assets_Completed.wav",
}
_CUE_NOTES = {
    "assets_Pending confirmation.wav": (660, 880),
    "assets_Completed.wav": (784, 1047, 1319),
}


def cue_for(state: str) -> str | None:
    """状态对应的音效文件名；不需要出声的状态返回 None。"""
    return CUE_FILES.get(state)


def _write_tone(path: Path, notes: tuple[int, ...]) -> None:
    rate = 22050
    length = rate // 10
    fade = rate // 100
    with wave.open(str(path), "wb") as handle:
        handle.setparams((1, 2, rate, 0, "NONE", "not compressed"))
        for hz in notes:
            samples = (
                int(
                    6500
                    * min(1, i / fade, (length - 1 - i) / fade)
                    * math.sin(math.tau * hz * i / rate)
                )
                for i in range(length)
            )
            handle.writeframesraw(struct.pack(f"<{length}h", *samples))


class AgentSfx(QObject):
    """按需创建音效播放器；同一状态重复触发时复用播放器。"""

    def __init__(self, assets_dir: Path, parent=None, volume: float = 0.8) -> None:
        super().__init__(parent)
        self._assets_dir = Path(assets_dir)
        self._volume = max(0.0, min(1.0, float(volume)))
        self._effects: dict[str, QSoundEffect] = {}
        self._generated: TemporaryDirectory | None = None

    def play(self, state: str) -> bool:
        """播放状态提示音；没有音效或无法创建临时文件时返回 False。"""
        name = cue_for(state)
        if name is None:
            return False
        effect = self._effects.get(name)
        if effect is None:
            effect = self._build(name)
            if effect is None:
                return False
            self._effects[name] = effect
        effect.play()
        return True

    def _build(self, name: str) -> QSoundEffect | None:
        path = self._assets_dir / name
        if not path.is_file():
            try:
                if self._generated is None:
                    self._generated = TemporaryDirectory(
                        prefix="idp-sfx-", ignore_cleanup_errors=True
                    )
                path = Path(self._generated.name) / name
                _write_tone(path, _CUE_NOTES[name])
            except OSError:
                # 音频是可选反馈，临时目录不可用时角标和气泡仍正常工作。
                return None
        # 与语音播报独立，避免状态音效打断 TTS。
        effect = QSoundEffect(self)
        effect.setSource(QUrl.fromLocalFile(str(path)))
        effect.setVolume(self._volume)
        return effect
