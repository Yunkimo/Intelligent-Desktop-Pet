"""米饭入口图标测试：素材加载、缺失降级与鼠标穿透属性。"""

from pathlib import Path

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QPixmap

from pet.rice_button import ICON_HEIGHT, RiceButton


def _write_icon(tmp_path) -> Path:
    pixmap = QPixmap(135, 129)
    pixmap.fill(Qt.GlobalColor.yellow)
    path = tmp_path / "Rice.png"
    assert pixmap.save(str(path))
    return path


def test_icon_is_scaled_to_fixed_height(tmp_path, qapp):
    button = RiceButton(_write_icon(tmp_path))

    assert button.height() == ICON_HEIGHT
    assert button.width() > 0
    assert button.pixmap() is not None and not button.pixmap().isNull()


def test_missing_asset_falls_back_to_text(tmp_path, qapp):
    button = RiceButton(tmp_path / "not-there.png")

    assert button.text() == "米"
    assert button.width() == button.height() == ICON_HEIGHT


def test_button_lets_mouse_events_through(tmp_path, qapp):
    """图标不抢鼠标事件，点击与拖拽统一由桌宠窗口判定。"""
    button = RiceButton(_write_icon(tmp_path))

    assert button.testAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents) is True
