"""把 Claude Code 回合状态 hook 合并写入本机 .claude/settings.local.json。

setup.bat 在安装依赖后自动调用；也可手动运行：

    .venv/Scripts/python scripts/install_claude_status_hook.py

只添加桌宠需要的 hook，保留已有的 hooks / permissions 等配置；重复运行不会
重复添加。该文件是个人本地配置，已被全局 gitignore，不会提交到仓库。
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent.parent
HOOK_SCRIPT = PROJECT_DIR / "scripts" / "claude_status_hook.py"
DEFAULT_SETTINGS = PROJECT_DIR / ".claude" / "settings.local.json"

# 覆盖一个完整回合：开始处理、工具执行、权限确认、完成、会话起止
EVENTS = (
    "UserPromptSubmit",
    "PreToolUse",
    "PostToolUse",
    "Notification",
    "Stop",
    "SessionStart",
    "SessionEnd",
)


def _command(python_exe: Path, hook_script: Path) -> str:
    """生成带引号的命令，兼容含空格的安装路径。

    脚本文件只在桌宠分支存在；切到 develop 等分支时直接执行会以退出码 2 结束，
    而 Claude Code 把 PreToolUse 的退出码 2 视为阻止调用。这里先用 Python 判断
    文件是否存在，缺失时静默以 0 退出，避免切换分支后整个会话被 hook 卡死。
    """
    code = (
        f"import os,runpy; p=r'{hook_script.as_posix()}'; "
        "os.path.exists(p) and runpy.run_path(p, run_name='__main__')"
    )
    return f'"{python_exe.as_posix()}" -c "{code}"'


def _normalized(command: str) -> str:
    return command.replace("\\", "/").strip()


def _handler_uses_script(handler: dict, hook_script: Path) -> bool:
    """判断已有 handler 是否指向本项目的状态脚本（兼容旧的直接调用格式）。"""
    command = str(handler.get("command") or "").replace("\\", "/").replace('"', "")
    return hook_script.as_posix() in command


def _atomic_write(path: Path, data: dict) -> None:
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".settings-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
            f.write("\n")
        os.replace(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def install(settings_path: Path, python_exe: Path, hook_script: Path) -> list[str]:
    """合并写入 hooks，返回本次新增的事件名列表。

    已有配置文件损坏或结构异常时抛出 ValueError，且不修改原文件。
    """
    settings_path = Path(settings_path)
    data: dict = {}
    if settings_path.exists():
        try:
            data = json.loads(settings_path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise ValueError(f"无法读取 {settings_path}: {exc}") from exc
        if not isinstance(data, dict):
            raise ValueError(f"{settings_path} 顶层不是 JSON 对象")

    hooks = data.setdefault("hooks", {})
    if not isinstance(hooks, dict):
        raise ValueError(f"{settings_path} 的 hooks 不是 JSON 对象")

    hook_script = Path(hook_script)
    command = _command(Path(python_exe), hook_script)
    handler = {"type": "command", "command": command, "timeout": 5}
    added: list[str] = []
    for event in EVENTS:
        groups = hooks.setdefault(event, [])
        if not isinstance(groups, list):
            raise ValueError(f"{settings_path} 的 hooks.{event} 不是数组")
        matched = False
        for group in groups:
            if not isinstance(group, dict):
                continue
            for existing in group.get("hooks") or []:
                if not isinstance(existing, dict):
                    continue
                if existing.get("type") != "command":
                    continue
                if not _handler_uses_script(existing, hook_script):
                    continue
                matched = True
                if _normalized(str(existing.get("command") or "")) != _normalized(command):
                    # 旧版直接调用脚本，升级为缺失时静默退出的写法
                    existing["command"] = command
                    existing["timeout"] = 5
                    added.append(event)
        if not matched:
            groups.append({"hooks": [dict(handler)]})
            added.append(event)

    if added:
        settings_path.parent.mkdir(parents=True, exist_ok=True)
        _atomic_write(settings_path, data)
    return added


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="写入桌宠的 Claude Code 状态 hooks")
    parser.add_argument("--settings", type=Path, default=DEFAULT_SETTINGS)
    parser.add_argument("--python", type=Path, default=Path(sys.executable))
    parser.add_argument("--script", type=Path, default=HOOK_SCRIPT)
    args = parser.parse_args(argv)

    try:
        added = install(args.settings, args.python, args.script)
    except (OSError, ValueError) as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        return 1

    if added:
        print(f"已写入 Claude Code 状态 hooks：{args.settings}")
        print(f"新增事件：{', '.join(added)}")
        print("重启 Claude Code 后生效。")
    else:
        print(f"Claude Code 状态 hooks 已存在，无需修改：{args.settings}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
