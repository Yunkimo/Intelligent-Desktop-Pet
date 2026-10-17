"""形象抽象层（策略模式）。

PetWindow 只依赖 Avatar 接口，不关心底层渲染实现，便于日后扩展新引擎
（如 Spine、视频形象）。当前仅实现图片 / 动图精灵引擎。
"""

from abc import ABC, abstractmethod
from pathlib import Path

from PyQt6.QtWidgets import QWidget

from .sprite import PetSprite


class Avatar(ABC):
    """形象引擎抽象基类：对外暴露统一接口，隐藏渲染实现差异。"""

    def __init__(self, parent: QWidget | None = None) -> None:
        self.widget: QWidget = self._build(parent)

    @abstractmethod
    def _build(self, parent: QWidget | None) -> QWidget:
        """构造底层控件（策略的具体实现）。"""

    @abstractmethod
    def react(self, event: str) -> None:
        """对外部事件做出动作（如 speak / poke）；不支持动作的引擎可空实现。"""

    def set_appearance(self, path: Path, size: int) -> None:
        """运行时更换形象；仅支持换图的引擎覆写。"""

    def clear(self) -> None:
        """释放当前形象占用的资源（图片文件句柄等）；无资源需释放的引擎保持空实现。"""


class SpriteAvatar(Avatar):
    """图片 / 动图精灵引擎（QLabel + QPixmap / QMovie）。"""

    def __init__(
        self, assets_dir: Path, frames: list[str], size: int, parent: QWidget | None = None
    ) -> None:
        self._assets_dir = assets_dir
        self._frames = frames
        self._size = size
        super().__init__(parent)

    def _build(self, parent: QWidget | None) -> QWidget:
        return PetSprite(self._assets_dir, self._frames, self._size, parent=parent)

    def react(self, event: str) -> None:
        return  # 静态精灵暂无对应动作

    def set_appearance(self, path: Path, size: int) -> None:
        self._size = size
        self.widget.set_image(path, size)  # type: ignore[attr-defined]

    def clear(self) -> None:
        self.widget.clear()  # type: ignore[attr-defined]


def create_avatar(settings, parent: QWidget | None = None) -> Avatar:
    """按配置构造形象引擎；当前固定为图片精灵。"""
    return SpriteAvatar(settings.assets_dir, settings.frames, settings.sprite_size, parent=parent)
