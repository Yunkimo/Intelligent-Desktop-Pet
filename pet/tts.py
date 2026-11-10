"""语音合成：edge-tts 生成 mp3。纯 Python（播放由 UI 层用 QMediaPlayer 完成）。"""

import asyncio
import json
import logging
import re
import subprocess
import sys
import tempfile
from pathlib import Path

import edge_tts

from .config import DEFAULT_TTS_TIMEOUT_SECONDS, DEFAULT_TTS_VOICE

logger = logging.getLogger(__name__)

# emoji、装饰符号、变体选择符与零宽连接符：合成时会被逐个念出来，直接去掉
_EMOJI = re.compile(
    "["
    "\U0001f300-\U0001faff"  # 表情、图形符号、补充符号
    "\U0001f1e6-\U0001f1ff"  # 区域指示符（国旗）
    "\U0001f000-\U0001f0ff"  # 麻将/扑克等
    "☀-➿"  # 杂项符号与装饰符号
    "←-⇿"  # 箭头
    "⬀-⯿"
    "️‍⃣"  # 变体选择符、ZWJ、组合键帽
    "]+"
)
_MARKDOWN = re.compile(r"(\*\*|__|`{1,3}|~~|\*(?!\s))")
_PREFIX = re.compile(r"(?m)^\s*(?:[#>]+\s*|[-*•]\s+|\d+[.)]\s+)")
_SPACES = re.compile(r"[ \t]{2,}")
# 表格：分隔行（|---|---|）整行丢掉，数据行把竖线换成逗号，避免念出「竖线横线」
_TABLE_RULE = re.compile(r"(?m)^[ \t]*\|?[ \t|:-]*-{3,}[ \t|:-]*\|?[ \t]*$")
_TABLE_ROW = re.compile(r"(?m)^[ \t]*\|(.+)\|[ \t]*$")


def sanitize_for_speech(text: str) -> str:
    """把回复整理成适合朗读的文本：去掉 emoji 与 Markdown 记号，压缩空白。

    只影响朗读，气泡里显示的原文不变。
    """
    cleaned = _EMOJI.sub("", text)
    cleaned = _TABLE_RULE.sub("", cleaned)

    def _row(match: re.Match) -> str:
        cells = [cell.strip() for cell in match.group(1).split("|")]
        return "，".join(cell for cell in cells if cell)

    cleaned = _TABLE_ROW.sub(_row, cleaned)
    cleaned = _MARKDOWN.sub("", cleaned)
    cleaned = _PREFIX.sub("", cleaned)
    cleaned = cleaned.replace("|", "，")  # 非整行的竖线也不留
    cleaned = _SPACES.sub(" ", cleaned)
    cleaned = re.sub(r"\n{2,}", "\n", cleaned)
    return cleaned.strip()


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
        text = sanitize_for_speech(text)
        if not text:
            raise ValueError("去掉表情后没有可朗读的内容")
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
