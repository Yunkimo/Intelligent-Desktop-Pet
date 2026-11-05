"""后台线程：把网络/录音/推理从 UI 线程移走，用 Qt 信号回传结果。"""

import threading
from collections.abc import Callable

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


class ChatWorker(QThread):
    chunk = pyqtSignal(str)  # 流式增量
    status = pyqtSignal(str)  # 工具执行状态（如「正在安排日程…」）
    done = pyqtSignal(str)  # 完整回复
    error = pyqtSignal(str)

    def __init__(
        self, client, messages: list[dict], tools: dict | None = None, parent=None
    ) -> None:
        super().__init__(parent)
        self.client = client
        self.messages = messages
        self.tools = tools or {}

    def run(self) -> None:
        try:
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
    ) -> None:
        super().__init__(parent)
        self.engine = engine
        self.max_duration = max_duration
        self.review = review
        self.correct = correct
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

        def callback(indata, _frames, _time, _status):
            frames.append(indata.copy())

        try:
            stream = self._open_stream(callback)
            stream.start()
            # 阻塞直到用户点击停止，或达到最大时长
            self._stop.wait(timeout=self.max_duration)
            stream.stop()
            stream.close()
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
