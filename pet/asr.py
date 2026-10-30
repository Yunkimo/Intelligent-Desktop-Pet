"""语音识别：本地 faster-whisper。懒加载模型，纯 Python（录音在 worker 里做）。

transcribe 前做峰值归一化，避免录音音量过低导致漏识别；识别时启用 VAD 过滤
静音段，并用 initial_prompt 注入领域热词（课表/日程/提醒等），提升专有词识别率。
热词只作提示引导，不改模型本身。
"""

import numpy as np


class ASREngine:
    def __init__(self, model_size: str = "base", hotwords: str = "") -> None:
        self.model_size = model_size
        # 空格分隔的热词，作为 initial_prompt 引导识别（中文场景比 hotwords 参数更可靠）
        self.hotwords = (hotwords or "").strip()
        self.samplerate = 16000
        self._model = None

    def _load_model(self):
        if self._model is None:
            from faster_whisper import WhisperModel

            # int8 跑 CPU，速度和精度折中；首次会自动下载模型
            self._model = WhisperModel(self.model_size, device="cpu", compute_type="int8")
        return self._model

    @staticmethod
    def _normalize(audio: np.ndarray) -> np.ndarray:
        """峰值归一化到 0.9；静音或过弱信号原样返回，避免除零。"""
        peak = float(np.max(np.abs(audio))) if audio.size else 0.0
        if peak < 1e-4:
            return audio
        return (audio / peak * 0.9).astype(np.float32)

    def transcribe(self, audio) -> str:
        """audio 为 float32 单声道 numpy 数组（16kHz），返回转写文本。"""
        model = self._load_model()
        audio = self._normalize(np.asarray(audio, dtype=np.float32))
        segments, _info = model.transcribe(
            audio,
            language="zh",
            beam_size=5,
            vad_filter=True,
            condition_on_previous_text=False,
            initial_prompt=self.hotwords or None,
        )
        return "".join(seg.text for seg in segments).strip()
