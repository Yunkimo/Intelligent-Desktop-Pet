"""后台线程：把网络/录音/推理从 UI 线程移走，用 Qt 信号回传结果。"""

import threading

import numpy as np
import sounddevice as sd
from PyQt6.QtCore import QThread, pyqtSignal

from .agent import Agent


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
    error = pyqtSignal(str)

    def __init__(self, engine, max_duration: float = 15.0, parent=None) -> None:
        super().__init__(parent)
        self.engine = engine
        self.max_duration = max_duration
        self._stop = threading.Event()

    def request_stop(self) -> None:
        self._stop.set()

    def run(self) -> None:
        frames: list[np.ndarray] = []

        def callback(indata, _frames, _time, _status):
            frames.append(indata.copy())

        try:
            stream = sd.InputStream(
                samplerate=self.engine.samplerate,
                channels=1,
                dtype="float32",
                callback=callback,
            )
            stream.start()
            # 阻塞直到用户点击停止，或达到最大时长
            self._stop.wait(timeout=self.max_duration)
            stream.stop()
            stream.close()
        except Exception as exc:  # noqa: BLE001
            self.error.emit(f"录音失败：{exc}")
            return

        audio = np.concatenate(frames).flatten() if frames else np.zeros(0, dtype=np.float32)
        if audio.size == 0:
            self.error.emit("没有录到声音")
            return
        try:
            self.text.emit(self.engine.transcribe(audio))
        except Exception as exc:  # noqa: BLE001
            self.error.emit(f"转写失败：{exc}")


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
