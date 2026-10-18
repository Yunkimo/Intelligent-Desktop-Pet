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
