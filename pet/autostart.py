"""开机自启管理：Windows 注册表 Run 键指向 启动桌宠.bat。"""

import os
from pathlib import Path

try:
    import winreg
except ImportError:  # 非 Windows 没有 winreg
    winreg = None

from .paths import app_dir

_RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
_VALUE_NAME = "IntelligentDeskPet"


def _bat_path(bat_path: Path | None) -> Path:
    """返回待注册的启动脚本路径；未指定时用项目根目录的 启动桌宠.bat。"""
    if bat_path is None:
        return app_dir() / "启动桌宠.bat"
    return Path(bat_path).resolve()


def enable(bat_path: Path | None = None) -> bool:
    """注册开机自启；成功返回 True，非 Windows 或写入失败返回 False。"""
    if winreg is None:
        return False
    path = _bat_path(bat_path)
    try:
        with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, _RUN_KEY) as key:
            winreg.SetValueEx(key, _VALUE_NAME, 0, winreg.REG_SZ, f'"{path}"')
    except OSError:
        return False
    return True


def disable(bat_path: Path | None = None) -> bool:
    """移除开机自启；条目本就不存在视为成功，非 Windows 或失败返回 False。"""
    if winreg is None:
        return False
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
            winreg.DeleteValue(key, _VALUE_NAME)
    except FileNotFoundError:
        return True
    except OSError:
        return False
    return True


def is_enabled(bat_path: Path | None = None) -> bool:
    """查询注册表是否已指向指定启动脚本；非 Windows 或读取失败返回 False。"""
    if winreg is None:
        return False
    path = _bat_path(bat_path)
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _RUN_KEY) as key:
            value, _ = winreg.QueryValueEx(key, _VALUE_NAME)
    except OSError:
        return False
    # 注册表值允许带引号；比较时去掉引号并忽略路径大小写差异
    return os.path.normcase(value.strip('"')) == os.path.normcase(str(path))
