"""气泡折行逻辑测试（纯函数）+ 气泡基本行为测试。"""

from pet.bubble import wrap_text


def test_wrap_text_empty():
    assert wrap_text("", 100, len) == [""]


def test_wrap_text_wraps_long():
    # measure=len，即每字符宽 1 像素
    assert wrap_text("abcdef", 3, len) == ["abc", "def"]


def test_wrap_text_newline():
    assert wrap_text("ab\ncd", 10, len) == ["ab", "cd"]


def test_bubble_append(qapp):
    from pet.bubble import SpeechBubble

    b = SpeechBubble(timeout_ms=0)  # 0 = 不自动隐藏
    b.set_text("你好")
    assert b._text == "你好"
    b.append_chunk("呀")
    assert b._text == "你好呀"


def test_bubble_tail_direction_toggle(qapp):
    from pet.bubble import SpeechBubble

    b = SpeechBubble(timeout_ms=0)
    assert b._tail_up is False
    b.set_tail_up(True)
    assert b._tail_up is True
    b.set_tail_up(True)  # 幂等
    assert b._tail_up is True
    b.set_tail_up(False)
    assert b._tail_up is False


def test_bubble_placement_flips_toward_screen_center(qapp):
    from PyQt6.QtCore import QRect

    from pet.bubble import bubble_placement

    screen = QRect(0, 0, 1000, 700)
    # 形象在左下角：气泡应在形象上方、偏向屏幕中心（右），尾巴朝下
    avatar = QRect(40, 540, 300, 200)
    x, y, tail_up = bubble_placement(avatar, screen, 200, 60, 8)
    assert tail_up is False
    assert y < avatar.y()
    assert x > avatar.x()

    # 形象在右上角：气泡应翻到形象下方、偏向屏幕中心（左），尾巴朝上
    avatar = QRect(660, 40, 300, 200)
    x, y, tail_up = bubble_placement(avatar, screen, 200, 60, 8)
    assert tail_up is True
    assert y > avatar.y() + avatar.height()
    assert x < avatar.x() + avatar.width() // 2


def test_bubble_placement_clamped_to_screen(qapp):
    from PyQt6.QtCore import QRect

    from pet.bubble import bubble_placement

    # 形象贴屏幕左上角、气泡比下方空间还高：翻到下方并夹在可用区域内
    screen = QRect(0, 0, 1000, 300)
    avatar = QRect(0, 0, 300, 200)
    x, y, tail_up = bubble_placement(avatar, screen, 240, 160, 8)
    assert tail_up is True
    assert screen.left() <= x <= screen.right() - 240
    assert screen.top() <= y <= screen.bottom() - 160


def test_bubble_placement_above_override(qapp):
    from PyQt6.QtCore import QRect

    from pet.bubble import bubble_placement

    screen = QRect(0, 0, 1000, 700)
    # 形象在上半屏（默认翻到下方）：above=True 强制气泡在形象上方、尾巴朝下
    avatar = QRect(660, 40, 300, 200)
    x, y, tail_up = bubble_placement(avatar, screen, 200, 60, 8, above=True)
    assert tail_up is False
    assert y < avatar.y()

    # 形象在下半屏（默认在上方）：above=False 强制气泡在形象下方、尾巴朝上
    avatar = QRect(40, 400, 300, 200)
    x, y, tail_up = bubble_placement(avatar, screen, 200, 60, 8, above=False)
    assert tail_up is True
    assert y > avatar.y() + avatar.height()


def test_badge_placement_matches_bubble_when_no_bubble(qapp):
    from PyQt6.QtCore import QRect

    from pet.bubble import badge_placement, bubble_placement

    screen = QRect(0, 0, 1000, 700)
    anchor = QRect(40, 540, 300, 200)
    expected = bubble_placement(anchor, screen, 100, 20, 8)[:2]
    assert badge_placement(anchor, screen, 100, 20, 8) == expected


def test_badge_placement_stacks_above_visible_bubble(qapp):
    """气泡在桌宠上方且与角标重叠时，角标应叠到气泡外侧。"""
    from PyQt6.QtCore import QRect

    from pet.bubble import badge_placement

    screen = QRect(0, 0, 1000, 700)
    anchor = QRect(40, 540, 300, 200)
    bubble = QRect(165, 472, 200, 60)

    x, y = badge_placement(anchor, screen, 100, 20, 8, bubble)

    assert y == bubble.y() - 20 - 8
    assert not QRect(x, y, 100, 20).intersects(bubble)


def test_badge_placement_stacks_below_visible_bubble(qapp):
    """气泡在桌宠下方时，角标同样叠在气泡外侧（下方）。"""
    from PyQt6.QtCore import QRect

    from pet.bubble import badge_placement

    screen = QRect(0, 0, 1000, 700)
    anchor = QRect(660, 40, 300, 200)
    bubble = QRect(635, 248, 200, 60)

    x, y = badge_placement(anchor, screen, 100, 20, 8, bubble)

    assert y == bubble.y() + bubble.height() + 8
    assert not QRect(x, y, 100, 20).intersects(bubble)


def test_badge_placement_flips_side_when_screen_edge_lacks_room(qapp):
    """气泡贴屏幕顶边、外侧放不下角标时，翻到桌宠另一侧。"""
    from PyQt6.QtCore import QRect

    from pet.bubble import badge_placement

    screen = QRect(0, 0, 1000, 200)
    anchor = QRect(40, 68, 300, 70)
    bubble = QRect(165, 0, 200, 60)

    x, y = badge_placement(anchor, screen, 100, 20, 8, bubble)

    assert y > bubble.bottom()
    assert not QRect(x, y, 100, 20).intersects(bubble)


def test_bubble_emits_visibility_changes(qapp):
    from pet.bubble import SpeechBubble

    bubble = SpeechBubble(timeout_ms=0)
    events: list[bool] = []
    bubble.visibility_changed.connect(events.append)

    bubble.set_text("你好")
    qapp.processEvents()
    bubble.hide()
    qapp.processEvents()

    assert events == [True, False]
