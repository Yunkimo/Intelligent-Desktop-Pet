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


def test_badge_hides_on_idle_and_unknown_fallback(qapp):
    badge = StatusBadge()
    badge.set_state("working")
    badge.set_state("idle")
    assert badge.isHidden()

    badge.set_state("不存在的状态")
    assert not badge.isHidden()
    assert badge.text() == "Claude 状态未知"


def test_badge_paints_rounded_background(qapp):
    """半透明顶层窗口不会绘制样式表背景，需由 paintEvent 自行画出胶囊底。"""
    badge = StatusBadge()
    badge.set_state("working")

    image = badge.grab().toImage()
    cx, cy = image.width() // 2, image.height() // 2
    # 中心是实心底色，左边缘是强调色边框，圆角处透明
    assert image.pixelColor(cx, cy).name() == "#e8f0fe"
    assert image.pixelColor(0, cy).name() != "#e8f0fe"
    assert image.pixelColor(0, 0).alpha() == 0
