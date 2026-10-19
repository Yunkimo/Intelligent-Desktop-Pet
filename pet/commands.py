"""命令模式：把菜单动作封装成可执行的命令对象。

桌宠右键菜单与系统托盘菜单是「调用者」，窗口方法是「接收者」：调用者只负责按
固定顺序列出 Command / Submenu，触发时通过 populate_menu 转发 execute()，不直接
操作窗口。checkable / checked / enabled 提供勾选与置灰能力，两类菜单共用。
"""

from dataclasses import dataclass
from typing import Callable

from PyQt6.QtWidgets import QMenu


@dataclass
class Command:
    """一条菜单命令：label 是菜单文本，execute 执行动作。"""

    label: str
    execute: Callable[[], None]
    checkable: bool = False
    checked: Callable[[], bool] | None = None
    enabled: Callable[[], bool] | None = None


class Submenu(Command):
    """子菜单条目：与 Command 同列排序，populate_menu 遇到时挂载其 QMenu。"""

    def __init__(self, menu: QMenu) -> None:
        super().__init__(label=menu.title(), execute=lambda: None)
        self.menu = menu


def populate_menu(menu: QMenu, commands: list[Command]) -> None:
    """按 commands 顺序往 menu 填动作：label 为动作文本，触发时执行。

    Submenu 条目用 addMenu 挂载，与普通命令保持同一顺序；checkable 命令按
    checked() 设置初始勾选态，enabled() 为 False 的命令直接置灰。
    """
    for cmd in commands:
        if isinstance(cmd, Submenu):
            # addMenu 会把子菜单所有权转交父菜单（C++ 侧 parent，Python 包装随之保活）。
            # 不要先 setParent：那会清掉子菜单的 Qt::Popup 窗口标志，子菜单便不再以独立
            # 弹出层显示，其条目会与父菜单项重叠（真机复现的重叠回归）。
            menu.addMenu(cmd.menu)
            continue
        action = menu.addAction(cmd.label)
        if cmd.checkable:
            action.setCheckable(True)
            if cmd.checked is not None:
                action.setChecked(cmd.checked())
        if cmd.enabled is not None and not cmd.enabled():
            action.setEnabled(False)
        action.triggered.connect(lambda _checked=False, command=cmd: command.execute())
