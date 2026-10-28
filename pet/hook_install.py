"""状态钩子安装封装：监控开关启用时调用，把钩子写入 Claude Code / Codex 配置。

scripts/ 是无 __init__.py 的脚本目录，pet/ 不通过包导入依赖它；这里按绝对路径
（由 pet 包自身位置推导）用 importlib 加载安装脚本，不依赖启动时的工作目录。
安装器只做一次小 JSON 读取 + 原子写入（毫秒级，无网络、无子进程），
不会长时间占用 UI 线程。
"""

from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path
from types import ModuleType

from .paths import app_dir

_SCRIPT_DIR = app_dir() / "scripts"


def _load_installer(filename: str) -> ModuleType:
    """按文件名加载 scripts/ 下的安装脚本模块。"""
    path = _SCRIPT_DIR / filename
    if not path.is_file():
        raise ImportError(f"找不到安装脚本：{path}")
    spec = importlib.util.spec_from_file_location(path.stem, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"无法加载安装脚本：{path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def ensure_claude_hooks() -> list[str]:
    """把 Claude Code 状态钩子合并写入本机 settings.local.json，返回新增事件名。"""
    module = _load_installer("install_claude_status_hook.py")
    return module.install(module.DEFAULT_SETTINGS, Path(sys.executable), module.HOOK_SCRIPT)


def ensure_codex_hooks() -> list[str]:
    """把 Codex 状态钩子合并写入本机 hooks.json，返回新增事件名。"""
    module = _load_installer("install_codex_status_hook.py")
    return module.install(module.DEFAULT_SETTINGS, Path(sys.executable), module.HOOK_SCRIPT)


def claude_code_installed() -> bool:
    """探测是否安装过 Claude Code（存在用户级 ~/.claude 目录）。"""
    return (Path.home() / ".claude").exists()


def codex_installed() -> bool:
    """探测是否安装过 Codex（优先 CODEX_HOME，其次用户级 ~/.codex 目录）。"""
    return Path(os.environ.get("CODEX_HOME") or Path.home() / ".codex").exists()
