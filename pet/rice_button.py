"""桌宠右下角的 Token 用量入口：一个米饭图标。

图标是主窗口的子控件，窗口移动时由 Qt 自动带走，物理上无法与桌宠分离。为使点击
与拖拽共用同一套状态机，图标本身**不接收鼠标事件**（WA_TransparentForMouseEvents），
命中判定与光标提示全部由 PetWindow 负责；素材缺失时降级成文字块，仍可点击。
"""

from pathlib import Path

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QPixmap
from PyQt6.QtWidgets import QLabel

ICON_HEIGHT = 44
_FALLBACK_STYLE = (
    "border-radius: 8px; background: rgba(255, 255, 255, 170); color: #444; font-size: 18px;"
)


class RiceButton(QLabel):
    """用量入口图标；只负责显示，交互由父窗口接管。"""

    def __init__(self, icon_path: Path, parent=None, height: int = ICON_HEIGHT) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        # 点击交给父窗口统一命中测试，否则会吃掉拖拽与「唤出输入框」
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self._load(Path(icon_path), height)

    def _load(self, icon_path: Path, height: int) -> None:
        pixmap = QPixmap(str(icon_path))
        if pixmap.isNull():
            self._build_fallback(height)
            return
        scaled = pixmap.scaledToHeight(height, Qt.TransformationMode.SmoothTransformation)
        self.setPixmap(scaled)
        self.setFixedSize(scaled.size())

    def _build_fallback(self, height: int) -> None:
        """素材缺失时给一个同尺寸的文字块，保证入口始终可用。"""
        self.setText("米")
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setStyleSheet(_FALLBACK_STYLE)
        self.setFixedSize(height, height)
