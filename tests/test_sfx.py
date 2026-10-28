"""Agent 状态音效测试：状态到音效文件的映射与缺失文件的降级。"""

import wave
from pathlib import Path

from pet.sfx import CUE_FILES, AgentSfx, cue_for


def _write_wav(path: Path, seconds: float = 0.05) -> Path:
    """写一段极短的静音 wav，作为可用素材。"""
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(8000)
        handle.writeframes(b"\x00\x00" * int(8000 * seconds))
    return path


def test_only_waiting_and_done_have_cues():
    assert cue_for("waiting") == "assets_Pending confirmation.wav"
    assert cue_for("done") == "assets_Completed.wav"
    for state in ("working", "idle", "unknown", ""):
        assert cue_for(state) is None
    assert set(CUE_FILES) == {"waiting", "done"}


def test_missing_file_is_silently_skipped(qapp, tmp_path):
    sfx = AgentSfx(tmp_path)
    assert sfx.play("waiting") is False
    assert sfx._effects == {}


def test_no_cue_state_returns_false(qapp, tmp_path):
    sfx = AgentSfx(tmp_path)
    assert sfx.play("working") is False


def test_existing_cue_is_loaded_once_and_reused(qapp, tmp_path):
    _write_wav(tmp_path / "assets_Completed.wav")
    sfx = AgentSfx(tmp_path)

    assert sfx.play("done") is True
    first = sfx._effects["assets_Completed.wav"]
    assert sfx.play("done") is True
    assert sfx._effects["assets_Completed.wav"] is first  # 不重复创建播放器


def test_volume_is_clamped(qapp, tmp_path):
    assert AgentSfx(tmp_path, volume=5.0)._volume == 1.0
    assert AgentSfx(tmp_path, volume=-1)._volume == 0.0
