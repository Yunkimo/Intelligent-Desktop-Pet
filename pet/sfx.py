"""Agent 状态音效：待确认与完成各播一段本地 wav。

音效文件缺失时静默跳过，不报错也不影响角标与气泡。用 QSoundEffect 而不是复用
TTS 的 QMediaPlayer，避免打断正在播报的回复，也省去临时文件清理。
"""

from pathlib import Path

from PyQt6.QtCore import QObject, QUrl
from PyQt6.QtMultimedia import QSoundEffect

CUE_FILES = {
    "waiting": "assets_Pending confirmation.wav",
    "done": "assets_Completed.wav",
}


def cue_for(state: str) -> str | None:
    """状态对应的音效文件名；不需要出声的状态返回 None。"""
    return CUE_FILES.get(state)


class AgentSfx(QObject):
    """按需创建音效播放器；同一状态重复触发时从头重播。"""

    def __init__(self, assets_dir: Path, parent=None, volume: float = 0.8) -> None:
        super().__init__(parent)
        self._assets_dir = Path(assets_dir)
        self._volume = max(0.0, min(1.0, float(volume)))
        self._effects: dict[str, QSoundEffect] = {}

    def play(self, state: str) -> bool:
        """播放该状态对应的提示音；没有对应音效或文件缺失时返回 False。"""
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
            return None
        effect = QSoundEffect(self)
        effect.setSource(QUrl.fromLocalFile(str(path)))
        effect.setVolume(self._volume)
        return effect
