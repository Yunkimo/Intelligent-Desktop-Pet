"""用量入口在桌宠窗口里的行为：定位、跟随、点击与拖拽分流。"""

from unittest.mock import Mock

from PyQt6.QtCore import QEvent, QPointF, Qt
from PyQt6.QtGui import QMouseEvent
from PyQt6.QtWidgets import QWidget

from pet.window import PetWindow

_W, _H = 400, 352
_SW, _SH = 200, 300


def _bare_window(tmp_path) -> PetWindow:
    """只初始化 QWidget 基类，手工挂上布局需要的最小控件集合。"""
    window = PetWindow.__new__(PetWindow)
    QWidget.__init__(window)
    window.resize(_W, _H)

    avatar_widget = QWidget(window)
    avatar_widget.setFixedSize(_SW, _SH)
    window.avatar = type("Avatar", (), {"widget": avatar_widget})()

    input_box = QWidget(window)
    input_box.setFixedSize(240, 36)
    window.input = input_box

    from pet.rice_button import RiceButton

    window.rice = RiceButton(tmp_path / "missing.png", parent=window)
    window.bubble = Mock()
    window._press_pos = None
    window._moved = False
    window._position_bubble = Mock()
    window._position_status_badge = Mock()
    return window


def _mouse(kind, local, global_pos, buttons=Qt.MouseButton.NoButton):
    local_point = QPointF(local) if hasattr(local, "x") else QPointF(*local)
    return QMouseEvent(
        kind,
        local_point,
        QPointF(*global_pos),
        Qt.MouseButton.LeftButton,
        buttons,
        Qt.KeyboardModifier.NoModifier,
    )


def test_rice_sits_inside_avatar_bottom_right(tmp_path, qapp):
    window = _bare_window(tmp_path)
    window._layout_children()

    rice = window.rice.geometry()
    avatar = window.avatar.widget.geometry()
    assert avatar.right() > rice.right()
    assert avatar.bottom() > rice.bottom()
    assert rice.right() > avatar.center().x()
    assert rice.bottom() > avatar.center().y()


def test_rice_follows_window_move(tmp_path, qapp):
    window = _bare_window(tmp_path)
    window._layout_children()
    before = window.rice.mapToGlobal(window.rice.rect().topLeft())

    window.move(window.pos().x() + 30, window.pos().y() + 40)
    after = window.rice.mapToGlobal(window.rice.rect().topLeft())

    assert after.x() - before.x() == 30
    assert after.y() - before.y() == 40


def test_click_on_rice_opens_usage_not_input(tmp_path, qapp):
    window = _bare_window(tmp_path)
    window._layout_children()
    window._show_usage_dialog = Mock()
    window.toggle_input = Mock()

    center = window.rice.geometry().center()
    window.mousePressEvent(
        _mouse(QEvent.Type.MouseButtonPress, center, (500, 500), buttons=Qt.MouseButton.LeftButton)
    )
    window.mouseReleaseEvent(_mouse(QEvent.Type.MouseButtonRelease, center, (500, 500)))

    window._show_usage_dialog.assert_called_once()
    window.toggle_input.assert_not_called()


def test_click_on_avatar_still_toggles_input(tmp_path, qapp):
    window = _bare_window(tmp_path)
    window._layout_children()
    window._show_usage_dialog = Mock()
    window.toggle_input = Mock()

    center = window.avatar.widget.geometry().center()
    window.mousePressEvent(
        _mouse(QEvent.Type.MouseButtonPress, center, (500, 500), buttons=Qt.MouseButton.LeftButton)
    )
    window.mouseReleaseEvent(_mouse(QEvent.Type.MouseButtonRelease, center, (500, 500)))

    window.toggle_input.assert_called_once()
    window._show_usage_dialog.assert_not_called()


def test_dragging_from_rice_moves_window_without_opening_dialog(tmp_path, qapp):
    """从米饭图标按下也能拖走桌宠，且松手时不弹用量窗口。"""
    window = _bare_window(tmp_path)
    window._layout_children()
    window._show_usage_dialog = Mock()
    window.toggle_input = Mock()
    start = window.pos()

    center = window.rice.geometry().center()
    window.mousePressEvent(
        _mouse(QEvent.Type.MouseButtonPress, center, (500, 500), buttons=Qt.MouseButton.LeftButton)
    )
    window.mouseMoveEvent(
        _mouse(QEvent.Type.MouseMove, center, (540, 520), buttons=Qt.MouseButton.LeftButton)
    )
    window.mouseReleaseEvent(_mouse(QEvent.Type.MouseButtonRelease, center, (540, 520)))

    assert window.pos() != start
    window._show_usage_dialog.assert_not_called()
    window.toggle_input.assert_not_called()


def test_hover_over_rice_shows_pointing_cursor(tmp_path, qapp):
    window = _bare_window(tmp_path)
    window._layout_children()

    window.mouseMoveEvent(
        _mouse(QEvent.Type.MouseMove, window.rice.geometry().center(), (500, 500))
    )
    assert window.cursor().shape() == Qt.CursorShape.PointingHandCursor

    window.mouseMoveEvent(_mouse(QEvent.Type.MouseMove, (5, 5), (500, 500)))
    assert window.cursor().shape() == Qt.CursorShape.ArrowCursor


def test_missing_rice_asset_keeps_entry_usable(tmp_path, qapp):
    window = _bare_window(tmp_path)
    assert window.rice.text() == "米"
    window._layout_children()
    assert window.rice.geometry().width() > 0
