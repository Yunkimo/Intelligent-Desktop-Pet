"""后台线程：把网络/录音/推理从 UI 线程移走，用 Qt 信号回传结果。"""

import threading
from collections.abc import Callable
from uuid import uuid4

import numpy as np
import sounddevice as sd
from PyQt6.QtCore import QThread, pyqtSignal

from .agent import Agent


def _refresh_audio_devices() -> None:
    """重建 PortAudio 设备列表。

    蓝牙耳机等设备热插拔后，PortAudio 缓存的默认设备可能指向已消失的索引，
    甚至变成 -1，此后每次录音都会报「Error querying device -1」。
    """
    try:
        sd._terminate()
        sd._initialize()
    except Exception:  # noqa: BLE001
        pass


def _first_input_device() -> int | None:
    """返回第一个能录音的设备索引；没有输入设备时返回 None。"""
    try:
        for index, info in enumerate(sd.query_devices()):
            if int(info["max_input_channels"]) > 0:
                return index
    except Exception:  # noqa: BLE001
        pass
    return None


# 判定「正在说话」的 RMS 阈值；低于它连续若干秒即视为一句话说完
_SPEECH_RMS = 0.005


class _SilenceGate:
    """按采样数累计连续静默时长，避免长时间空录一直停在「聆听中」。"""

    def __init__(
        self, samplerate: int, silence_secs: float, threshold: float = _SPEECH_RMS
    ) -> None:
        self._threshold = threshold
        self._limit = max(1, int(samplerate * silence_secs))
        self._silent = 0

    def feed(self, block: np.ndarray) -> bool:
        """喂入一块音频；返回 True 表示静默已超过阈值。"""
        samples = np.asarray(block, dtype=np.float64).reshape(-1)
        rms = float(np.sqrt(np.mean(samples**2))) if samples.size else 0.0
        if rms >= self._threshold:
            self._silent = 0
        else:
            self._silent += samples.size
        return self._silent >= self._limit


class ChatWorker(QThread):
    chunk = pyqtSignal(str)  # 流式增量
    status = pyqtSignal(str)  # 工具执行状态（如「正在安排日程…」）
    done = pyqtSignal(str)  # 完整回复
    capture_finished = pyqtSignal(str, bool)  # 回复及是否需要用户补充
    error = pyqtSignal(str)

    def __init__(
        self,
        client,
        messages: list[dict],
        tools: dict | None = None,
        parent=None,
        *,
        backend=None,
        pending=None,
        capture_retry=None,
    ) -> None:
        super().__init__(parent)
        self.client = client
        self.messages = messages
        self.tools = tools or {}
        self.backend = backend
        self.pending = pending
        self.capture_retry = capture_retry

    def _capture(self) -> tuple[str, bool] | None:
        if self.backend is None or not self.backend.session_token:
            return None
        text = self.messages[-1]["content"]
        if not isinstance(text, str):
            return None
        session = self.backend.session_token
        choice = text.strip()
        if self.pending and self.pending[0] == session:
            if choice == "取消":
                self.pending = None
                return "已退出本次选择。", False
            if choice not in self.pending[2]:
                return "请输入可选的序号，或输入「取消」。", False
            result = self.backend.confirm_capture(
                self.pending[1], self.pending[2][choice], self.pending[3]
            )
            self.pending = None
        else:
            self.pending = None
            request_id = (
                self.capture_retry[2]
                if self.capture_retry and self.capture_retry[:2] == (session, text)
                else uuid4().hex
            )
            self.capture_retry = (session, text, request_id)
            result = self.backend.capture_text(text, request_id)
            self.capture_retry = None
        if result["status"] == "not_action":
            return None
        choices = result.get("choices", [])
        message = result["message"]
        if choices:
            numbers = [str(i) for i in range(1, len(choices) + 1)]
            stage = result.get("stage", "item")
            selections = {
                number: int(number)
                for number, option in zip(numbers, choices, strict=True)
                if not option.get("disabled")
            }
            if stage == "reminder":
                selections["不提醒"] = len(choices)
                if not choices[0].get("disabled"):
                    selections.update({"默认": 1, "提前一小时": 1, "提前1小时": 1})
            self.pending = (session, result["request_id"], selections, stage)
            message += "\n" + "\n".join(
                f"{number}. {option.get('choice_label', option['label'])}"
                for number, option in zip(numbers, choices, strict=True)
            )
            message += "\n请回复序号，或输入「取消」。"
        return message, result["status"] == "needs_clarification"

    def run(self) -> None:
        try:
            if (reply := self._capture()) is not None:
                self.capture_finished.emit(*reply)
                return
            agent = Agent(self.client, self.tools)
            result = agent.run(self.messages, on_chunk=self.chunk.emit, on_status=self.status.emit)
            self.done.emit(result)
        except Exception as exc:  # noqa: BLE001
            self.error.emit(str(exc))


class ASRWorker(QThread):
    text = pyqtSignal(str)
    draft = pyqtSignal(str)
    status = pyqtSignal(str)
    error = pyqtSignal(str)

    def __init__(
        self,
        engine,
        max_duration: float = 15.0,
        parent=None,
        *,
        review: bool = False,
        correct: Callable[[str], str] | None = None,
        silence_secs: float = 3.0,
    ) -> None:
        super().__init__(parent)
        self.engine = engine
        self.max_duration = max_duration
        self.review = review
        self.correct = correct
        # 连续静默超过该时长就结束录音并识别（0 表示不启用）
        self.silence_secs = silence_secs
        self._stop = threading.Event()

    def request_stop(self) -> None:
        self._stop.set()

    def _open_stream(self, callback):
        """打开麦克风流；默认设备失效时重建设备列表并退到第一个可录音设备。"""
        kwargs = {
            "samplerate": self.engine.samplerate,
            "channels": 1,
            "dtype": "float32",
            "callback": callback,
        }
        try:
            return sd.InputStream(**kwargs)
        except Exception:  # noqa: BLE001
            _refresh_audio_devices()
            try:
                return sd.InputStream(**kwargs)
            except Exception as exc:
                device = _first_input_device()
                if device is None:
                    raise RuntimeError("没有可用的麦克风") from exc
                return sd.InputStream(device=device, **kwargs)

    def run(self) -> None:
        frames: list[np.ndarray] = []
        gate = (
            _SilenceGate(self.engine.samplerate, self.silence_secs)
            if self.silence_secs > 0
            else None
        )

        def callback(indata, _frames, _time, _status):
            frames.append(indata.copy())
            # 说到一半停下来也一样：静默够久就主动结束，用户不必再松手
            if gate is not None and gate.feed(indata):
                self._stop.set()

        try:
            with self._open_stream(callback):
                # 阻塞直到用户点击停止、静默超时，或达到最大时长
                self._stop.wait(timeout=self.max_duration)
        except Exception as exc:  # noqa: BLE001
            self.error.emit(f"录音失败：{exc}")
            return

        if self.isInterruptionRequested():
            return
        audio = np.concatenate(frames).flatten() if frames else np.zeros(0, dtype=np.float32)
        if audio.size == 0:
            self.error.emit("没有录到声音")
            return
        self.status.emit("正在识别语音…")
        try:
            text = self.engine.transcribe(audio)
        except Exception as exc:  # noqa: BLE001
            self.error.emit(f"转写失败：{exc}")
            return
        if self.isInterruptionRequested():
            return
        if not text or not self.review:
            self.text.emit(text)
            return
        if self.correct is not None:
            self.status.emit("正在 AI 校对…")
            try:
                text = self.correct(text) or text
            except Exception:  # 校对服务不可用时，保留原始转写。
                pass
        self.draft.emit(text)


class TTSWorker(QThread):
    ready = pyqtSignal(str)  # 合成完成，携带 mp3 路径
    error = pyqtSignal(str)

    def __init__(self, engine, text: str, parent=None) -> None:
        super().__init__(parent)
        self.engine = engine
        self.text = text

    def run(self) -> None:
        try:
            path = self.engine.synthesize(self.text)
            self.ready.emit(path)
        except Exception as exc:  # noqa: BLE001
            self.error.emit(str(exc))
