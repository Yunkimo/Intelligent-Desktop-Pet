"""语音识别：本地 faster-whisper。懒加载模型，纯 Python（录音在 worker 里做）。"""


class ASREngine:
    def __init__(self, model_size: str = "base") -> None:
        self.model_size = model_size
        self.samplerate = 16000
        self._model = None

    def _load_model(self):
        if self._model is None:
            from faster_whisper import WhisperModel

            # int8 跑 CPU，速度和精度折中；首次会自动下载模型
            self._model = WhisperModel(self.model_size, device="cpu", compute_type="int8")
        return self._model

    def transcribe(self, audio) -> str:
        """audio 为 float32 单声道 numpy 数组（16kHz），返回转写文本。"""
        model = self._load_model()
        segments, _info = model.transcribe(audio, language="zh", beam_size=5)
        return "".join(seg.text for seg in segments).strip()
