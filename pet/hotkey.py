"""全局语音快捷键：用 pynput 在后台监听键盘，长按开始录音、松开停止并识别。

pynput 的 Listener 跑在独立线程，回调里只做按键比对并发出 Qt 信号；
录音 / 识别等 UI 逻辑由窗口在主线程响应信号完成（跨线程用队列投递）。
"""

import threading

from pynput import keyboard
from PyQt6.QtCore import QObject, pyqtSignal

__all__ = ["parse_hotkey", "HotkeyManager"]

# 修饰键名 → pynput Key（左 / 右修饰键都算按下）
_MODIFIER_KEYS = {
    "ctrl": (keyboard.Key.ctrl, keyboard.Key.ctrl_l, keyboard.Key.ctrl_r),
    "control": (keyboard.Key.ctrl, keyboard.Key.ctrl_l, keyboard.Key.ctrl_r),
    "shift": (keyboard.Key.shift, keyboard.Key.shift_l, keyboard.Key.shift_r),
    "alt": (keyboard.Key.alt, keyboard.Key.alt_l, keyboard.Key.alt_r, keyboard.Key.alt_gr),
    "cmd": (keyboard.Key.cmd, keyboard.Key.cmd_l, keyboard.Key.cmd_r),
    "windows": (keyboard.Key.cmd, keyboard.Key.cmd_l, keyboard.Key.cmd_r),
}

# 非修饰特殊键名 → pynput Key
_SPECIAL_KEYS = {
    "space": keyboard.Key.space,
    "enter": keyboard.Key.enter,
    "tab": keyboard.Key.tab,
    "esc": keyboard.Key.esc,
    "backspace": keyboard.Key.backspace,
    "delete": keyboard.Key.delete,
    "up": keyboard.Key.up,
    "down": keyboard.Key.down,
    "left": keyboard.Key.left,
    "right": keyboard.Key.right,
    "home": keyboard.Key.home,
    "end": keyboard.Key.end,
    "page_up": keyboard.Key.page_up,
    "page_down": keyboard.Key.page_down,
    "insert": keyboard.Key.insert,
    "caps_lock": keyboard.Key.caps_lock,
}
for _i in range(1, 25):
    # pynput 的 Key 枚举各版本只定义到 f20，逐项 getattr 并跳过不存在的（如 f21~f24）
    key = getattr(keyboard.Key, f"f{_i}", None)
    if key is not None:
        _SPECIAL_KEYS[f"f{_i}"] = key


def parse_hotkey(hotkey: str) -> tuple[frozenset[str], str]:
    """把 'ctrl+shift+r' 或 '`' 解析为 (修饰键集合, 主键)。主键为最后一段。"""
    parts = [p.strip().lower() for p in hotkey.split("+") if p.strip()]
    if not parts:
        raise ValueError("快捷键不能为空")
    return frozenset(parts[:-1]), parts[-1]


def _to_key(name: str):
    """按键名 → pynput Key / KeyCode。"""
    if name in _SPECIAL_KEYS:
        return _SPECIAL_KEYS[name]
    if len(name) == 1:
        kc = keyboard.KeyCode.from_char(name)
        # 字母键在 Windows 上物理虚拟键码是大写码，归一以便修饰键组合按键位匹配
        if "a" <= name <= "z":
            kc = keyboard.KeyCode(char=name, vk=ord(name.upper()))
        return kc
    raise ValueError(f"未知按键：{name}")


class HotkeyManager(QObject):
    """后台监听全局键盘；主键按下发 pressed、松开发 released。"""

    pressed = pyqtSignal()
    released = pyqtSignal()

    def __init__(self, hotkey: str, parent=None) -> None:
        super().__init__(parent)
        self._modifiers, main = parse_hotkey(hotkey)
        self._main = _to_key(main)
        self._held: set = set()
        self._active = False
        self._listener: keyboard.Listener | None = None
        self._thread: threading.Thread | None = None

    # —— 生命周期 ——
    def start(self) -> None:
        if self._listener is not None:
            return
        self._listener = keyboard.Listener(on_press=self._on_press, on_release=self._on_release)
        self._thread = threading.Thread(
            target=self._listener.run, daemon=True, name="hotkey-listener"
        )
        self._thread.start()

    def stop(self) -> None:
        if self._listener is not None:
            self._listener.stop()
            self._listener = None
            self._thread = None

    # —— 匹配 ——
    def _is_modifier(self, key) -> bool:
        return any(key in keys for keys in _MODIFIER_KEYS.values())

    def _is_main(self, key) -> bool:
        target = self._main
        if isinstance(target, keyboard.KeyCode):
            # 字符匹配优先（反引号等符号键最可靠）；字符被修饰键改变时退回键位码
            if target.char is not None and getattr(key, "char", None) == target.char:
                return True
            tv = getattr(target, "vk", None)
            kv = getattr(key, "vk", None)
            return tv is not None and kv is not None and tv == kv
        return key == target

    def _mods_satisfied(self) -> bool:
        return all(self._has_mod(m) for m in self._modifiers)

    def _has_mod(self, name: str) -> bool:
        return any(k in self._held for k in _MODIFIER_KEYS.get(name, ()))

    # —— pynput 回调（监听线程内执行，只发信号）——
    def _on_press(self, key) -> None:
        if self._is_modifier(key):
            self._held.add(key)
            return
        if self._is_main(key) and self._mods_satisfied() and not self._active:
            self._active = True
            self.pressed.emit()

    def _on_release(self, key) -> None:
        if self._is_modifier(key):
            self._held.discard(key)
            return
        if self._is_main(key) and self._active:
            self._active = False
            self.released.emit()
