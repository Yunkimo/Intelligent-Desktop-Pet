"""Command 模式测试：用可变闭包变量模拟窗口状态，不构造 PetWindow，验证命令包装与
菜单填充行为。"""

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QMenu

from pet.commands import Command, Submenu, populate_menu


def _titled_menu(title: str, parent: QMenu | None = None) -> QMenu:
    # 子菜单构造时即带父级（真实代码里父级是窗口），保持 Qt::Popup 弹出行为与生命周期
    menu = QMenu(parent)
    menu.setTitle(title)
    return menu


def test_command_defaults():
    cmd = Command("a", lambda: None)
    assert cmd.label == "a"
    assert cmd.checkable is False
    assert cmd.checked is None
    assert cmd.enabled is None


def test_populate_menu_label_order(qapp):
    menu = QMenu()
    populate_menu(
        menu,
        [
            Command("切换图片…", lambda: None),
            Command("退出", lambda: None),
            Submenu(_titled_menu("切换人设", menu)),
            Command("测试后端连接", lambda: None),
        ],
    )
    assert [a.text() for a in menu.actions()] == [
        "切换图片…",
        "退出",
        "切换人设",
        "测试后端连接",
    ]


def test_submenu_keeps_nested_contents(qapp):
    sub = QMenu()
    populate_menu(sub, [Command("表情A", lambda: None)])
    menu = QMenu()
    populate_menu(menu, [Submenu(sub)])
    mounted = menu.actions()[0].menu()
    assert mounted is not None
    assert [a.text() for a in mounted.actions()] == ["表情A"]


def test_submenu_keeps_popup_flag(qapp):
    # 回归：setParent 会清掉 Qt::Popup，子菜单便不再以独立弹出层显示、条目与父菜单项重叠
    sub = QMenu()
    sub.setTitle("子菜单")
    menu = QMenu()
    populate_menu(menu, [Submenu(sub)])
    assert menu.actions()[0].menu() is sub
    assert bool(sub.windowFlags() & Qt.WindowType.Popup)


def test_submenu_survives_after_command_list_dropped(qapp):
    # Submenu / QMenu 仅由临时列表持有时，释放后子菜单也不应从父菜单消失
    menu = QMenu()

    def fill() -> None:
        populate_menu(menu, [Command("A", lambda: None), Submenu(_titled_menu("切换表情", menu))])

    fill()
    assert [a.text() for a in menu.actions()] == ["A", "切换表情"]
    assert menu.actions()[1].menu() is not None


def test_trigger_executes(qapp):
    calls: list[str] = []
    menu = QMenu()
    populate_menu(menu, [Command("a", lambda: calls.append("run"))])
    menu.actions()[0].trigger()
    assert calls == ["run"]


def test_populate_menu_checkable_initial_state(qapp):
    checked_menu = QMenu()
    populate_menu(
        checked_menu,
        [Command("当前模型", lambda: None, checkable=True, checked=lambda: True)],
    )
    action = checked_menu.actions()[0]
    assert action.isCheckable() is True
    assert action.isChecked() is True

    unchecked_menu = QMenu()
    populate_menu(
        unchecked_menu,
        [Command("当前模型", lambda: None, checkable=True, checked=lambda: False)],
    )
    assert unchecked_menu.actions()[0].isChecked() is False


def test_populate_menu_disabled_when_enabled_false(qapp):
    disabled_menu = QMenu()
    populate_menu(disabled_menu, [Command("A", lambda: None, enabled=lambda: False)])
    assert disabled_menu.actions()[0].isEnabled() is False

    enabled_menu = QMenu()
    populate_menu(enabled_menu, [Command("B", lambda: None, enabled=lambda: True)])
    assert enabled_menu.actions()[0].isEnabled() is True
