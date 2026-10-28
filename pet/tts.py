"""语音合成：edge-tts 生成 mp3。纯 Python（播放由 UI 层用 QMediaPlayer 完成）。"""

import asyncio
import json
import logging
import subprocess
import sys
import tempfile
from pathlib import Path

import edge_tts

from .config import DEFAULT_TTS_TIMEOUT_SECONDS, DEFAULT_TTS_VOICE

logger = logging.getLogger(__name__)
_WINDOWS_SYNTHESIS = """
$ErrorActionPreference = 'Stop'
$payload = [Console]::In.ReadToEnd() | ConvertFrom-Json
Add-Type -AssemblyName System.Speech
$speaker = New-Object System.Speech.Synthesis.SpeechSynthesizer
try {
    $speaker.SelectVoiceByHints(
        [System.Speech.Synthesis.VoiceGender]::NotSet,
        [System.Speech.Synthesis.VoiceAge]::NotSet,
        0, [System.Globalization.CultureInfo]::GetCultureInfo('zh-CN'))
    $speaker.SetOutputToWaveFile($payload.path)
    $speaker.Speak([string]$payload.text)
} finally { $speaker.Dispose() }
"""


class TTSEngine:
    def __init__(
        self,
        voice: str = DEFAULT_TTS_VOICE,
        rate: str = "+10%",
        pitch: str = "+20Hz",
        timeout: float = DEFAULT_TTS_TIMEOUT_SECONDS,
        windows_fallback: bool = True,
    ) -> None:
        self.voice = voice
        self.rate = rate
        self.pitch = pitch
        self.timeout = timeout
        self.windows_fallback = windows_fallback

    def synthesize(self, text: str) -> str:
        """把文本合成到临时 mp3 文件，返回路径。需在非异步线程里调用。"""
        tmp = tempfile.NamedTemporaryFile(suffix=".mp3", delete=False)
        tmp.close()

        async def _run() -> None:
            comm = edge_tts.Communicate(text, self.voice, rate=self.rate, pitch=self.pitch)
            await comm.save(tmp.name)

        async def bounded() -> None:
            await asyncio.wait_for(_run(), timeout=self.timeout)

        try:
            asyncio.run(bounded())
        except BaseException as exc:
            Path(tmp.name).unlink(missing_ok=True)
            if isinstance(exc, Exception) and self.windows_fallback and sys.platform == "win32":
                logger.warning("Online speech unavailable; using local Chinese voice")
                return self._synthesize_windows(text)
            raise
        return tmp.name

    def _synthesize_windows(self, text: str) -> str:
        """Windows 中文语音兜底；文本通过 JSON 标准输入传递，不拼接 shell。"""
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
            path = Path(tmp.name)
        try:
            subprocess.run(
                ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", _WINDOWS_SYNTHESIS],
                input=json.dumps({"text": text, "path": str(path)}),
                text=True,
                encoding="utf-8",
                capture_output=True,
                check=True,
                timeout=self.timeout,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            if path.stat().st_size <= 44:
                raise RuntimeError("本地语音未生成有效音频")
        except BaseException:
            path.unlink(missing_ok=True)
            raise
        return str(path)
