"""状态角标测试：文案、显隐与颜色样式。"""

from pet.status_badge import StatusBadge


def test_badge_shows_state_text(qapp):
    badge = StatusBadge()
    badge.set_state("working")
    assert not badge.isHidden()
    assert badge.text() == "Claude 处理中…"
    assert "#1f6feb" in badge.styleSheet()

    badge.set_state("waiting")
    assert badge.text() == "Claude 等你确认"
    assert "#9a6700" in badge.styleSheet()

    badge.set_state("done")
    assert badge.text() == "Claude 本轮完成"
    assert "#1a7f37" in badge.styleSheet()


def test_badge_stylesheet_parses_without_warning(qapp):
    """样式表必须能被 Qt 解析；多一个右花括号会在启动时打印解析警告。"""
    from PyQt6.QtCore import qInstallMessageHandler

    messages: list[str] = []
    previous = qInstallMessageHandler(lambda mode, context, message: messages.append(message))
    try:
        badge = StatusBadge()
        badge.set_state("working")
        badge.grab()
        qapp.processEvents()
    finally:
        qInstallMessageHandler(previous)

    assert [m for m in messages if "Could not parse stylesheet" in m] == []


def test_badge_hides_on_idle_and_unknown_fallback(qapp):
    badge = StatusBadge()
    badge.set_state("working")
    badge.set_state("idle")
    assert badge.isHidden()

    badge.set_state("不存在的状态")
    assert not badge.isHidden()
    assert badge.text() == "Claude 状态未知"


def test_badge_uses_configured_agent_name(qapp):
    badge = StatusBadge(agent_name="Codex")
    badge.set_state("waiting")
    assert badge.text() == "Codex 等你确认"


def test_badge_paints_rounded_background(qapp):
    """半透明顶层窗口不会绘制样式表背景，需由 paintEvent 自行画出胶囊底。"""
    badge = StatusBadge()
    badge.set_state("working")

    image = badge.grab().toImage()
    cy = image.height() // 2
    opaque = [
        image.pixelColor(x, y).name()
        for x in range(image.width())
        for y in range(image.height())
        if image.pixelColor(x, y).alpha() > 0
    ]
    # 胶囊内铺满状态底色，左边缘是实心边框，圆角处透明
    assert opaque.count("#e8f0fe") > image.width()
    assert image.pixelColor(0, cy).alpha() > 200  # 圆角抗锯齿会有少量半透明
    assert image.pixelColor(0, cy).name() != "#e8f0fe"
    assert image.pixelColor(0, 0).alpha() == 0


def _mouse_event(event_type, global_pos, button, buttons):
    from PyQt6.QtCore import QPointF, Qt
    from PyQt6.QtGui import QMouseEvent

    return QMouseEvent(
        event_type,
        QPointF(2, 2),
        QPointF(*global_pos),
        button,
        buttons,
        Qt.KeyboardModifier.NoModifier,
    )


def test_badge_receives_mouse_events(qapp):
    """角标须接受鼠标才能拖拽与双击，不能设置 WA_TransparentForMouseEvents。"""
    from PyQt6.QtCore import Qt

    badge = StatusBadge()
    assert not badge.testAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
    badge.close()


def test_badge_drag_moves_and_marks_manual(qapp):
    """按下左键拖过阈值后，角标跟随位移并被标记为手动位置。"""
    from PyQt6.QtCore import QEvent, QPoint, Qt

    badge = StatusBadge()
    badge.set_state("working")
    badge.show()
    qapp.processEvents()
    start = badge.pos()

    badge.mousePressEvent(
        _mouse_event(
            QEvent.Type.MouseButtonPress,
            (10, 10),
            Qt.MouseButton.LeftButton,
            Qt.MouseButton.LeftButton,
        )
    )
    badge.mouseMoveEvent(
        _mouse_event(
            QEvent.Type.MouseMove, (30, 30), Qt.MouseButton.NoButton, Qt.MouseButton.LeftButton
        )
    )

    assert badge.is_manually_positioned is True
    assert badge.pos() == start + QPoint(20, 20)
    badge.close()


def test_badge_double_click_resets_manual_position(qapp):
    """双击清空手动位置并发出 position_reset，让窗口重新自动摆位。"""
    from PyQt6.QtCore import QEvent, Qt

    badge = StatusBadge()
    badge.set_state("working")
    badge.show()
    qapp.processEvents()

    badge._user_moved = True
    resets: list[bool] = []
    badge.position_reset.connect(lambda: resets.append(True))

    badge.mouseDoubleClickEvent(
        _mouse_event(
            QEvent.Type.MouseButtonDblClick,
            (10, 10),
            Qt.MouseButton.LeftButton,
            Qt.MouseButton.LeftButton,
        )
    )

    assert badge.is_manually_positioned is False
    assert resets == [True]
    badge.close()


def test_badge_drag_clamps_to_screen(qapp):
    """拖出可用区域时角标被夹回屏幕内，避免再也点不到它复位。"""
    from PyQt6.QtCore import QPoint
    from PyQt6.QtGui import QGuiApplication

    badge = StatusBadge()
    badge.set_state("working")
    badge.show()
    qapp.processEvents()

    geo = QGuiApplication.primaryScreen().availableGeometry()
    clamped = badge._clamp_to_screen(QPoint(geo.right() + 1000, geo.bottom() + 1000))
    assert clamped.x() <= geo.right()
    assert clamped.y() <= geo.bottom()
    badge.close()
