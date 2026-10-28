"""全局语音快捷键：解析与按键匹配测试（需要 pynput）。"""

import pytest

pytest.importorskip("pynput")

hotkey = pytest.importorskip("pet.hotkey")
from pynput import keyboard  # noqa: E402


def test_parse_single_key():
    mods, main = hotkey.parse_hotkey("`")
    assert mods == frozenset()
    assert main == "`"


def test_parse_combo():
    mods, main = hotkey.parse_hotkey("Ctrl+Shift+R")
    assert mods == frozenset({"ctrl", "shift"})
    assert main == "r"


def test_parse_default_ctrl_t():
    # 默认快捷键为 Ctrl+T（大小写不敏感）
    mods, main = hotkey.parse_hotkey("ctrl+t")
    assert mods == frozenset({"ctrl"})
    assert main == "t"


def test_parse_function_key():
    mods, main = hotkey.parse_hotkey("F8")
    assert mods == frozenset()
    assert main == "f8"


def test_function_key_range():
    # 回归：功能键逐项 getattr 并跳过不存在的（曾因 getattr(Key, "f21") 不带默认值
    # 直接抛 AttributeError 导致 import 失败）。pynput 定义的功能键数量随平台而异
    # （Linux 到 f20，Windows 到 f24），故断言必须与 hasattr 对齐，不能写死。
    assert "f1" in hotkey._SPECIAL_KEYS
    for i in range(1, 25):
        name = f"f{i}"
        assert (name in hotkey._SPECIAL_KEYS) == hasattr(keyboard.Key, name)


def test_parse_empty_raises():
    with pytest.raises(ValueError):
        hotkey.parse_hotkey("")


def test_match_plain_backtick():
    mgr = hotkey.HotkeyManager("`")
    assert mgr._is_main(keyboard.KeyCode.from_char("`"))
    assert not mgr._is_main(keyboard.KeyCode.from_char("a"))


def test_match_letter_combo_by_vk():
    mgr = hotkey.HotkeyManager("ctrl+r")
    # 修饰键会改变字符（ctrl+r 的 char 变成控制符），应按虚拟键码匹配
    assert mgr._is_main(keyboard.KeyCode.from_vk(ord("R")))
    assert not mgr._is_main(keyboard.KeyCode.from_vk(ord("X")))
