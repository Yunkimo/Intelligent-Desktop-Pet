"""Merge the desktop pet's status hooks into the user's Codex hooks.json."""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent.parent
HOOK_SCRIPT = PROJECT_DIR / "scripts" / "codex_status_hook.py"
CODEX_HOME = Path(os.environ.get("CODEX_HOME", Path.home() / ".codex"))
DEFAULT_SETTINGS = CODEX_HOME / "hooks.json"
EVENTS = (
    "SessionStart",
    "UserPromptSubmit",
    "PreToolUse",
    "PostToolUse",
    "PermissionRequest",
    "Stop",
    "Interrupt",
    "SessionEnd",
)


def _command(python_exe: Path, hook_script: Path) -> str:
    # Keep the hook a no-op after this clone is moved or the script is absent.
    script_literal = json.dumps(Path(hook_script).as_posix())
    code = f"import os,runpy; p={script_literal}; os.path.exists(p) and runpy.run_path(p, run_name='__main__')"
    if os.name == "nt":
        import base64

        # Encode the PowerShell script so the outer shell cannot reinterpret quotes.
        def quote(value: str) -> str:
            return "'" + value.replace("'", "''") + "'"

        script = f"if (Test-Path -LiteralPath {quote(str(hook_script))}) {{ & {quote(str(python_exe))} {quote(str(hook_script))} }}"
        encoded = base64.b64encode(script.encode("utf-16-le")).decode("ascii")
        return f"powershell.exe -NoProfile -NonInteractive -EncodedCommand {encoded}"
    import shlex

    return " ".join(shlex.quote(part) for part in (str(python_exe), "-c", code))


def _atomic_write(path: Path, data: dict) -> None:
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".hooks-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(data, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
        os.replace(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def install(settings_path: Path, python_exe: Path, hook_script: Path) -> list[str]:
    settings_path = Path(settings_path)
    data: dict = {}
    if settings_path.exists():
        try:
            data = json.loads(settings_path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise ValueError(f"Cannot read {settings_path}: {exc}") from exc
        if not isinstance(data, dict):
            raise ValueError(f"{settings_path} must contain a JSON object")
    hooks = data.setdefault("hooks", {})
    if not isinstance(hooks, dict):
        raise ValueError(f"{settings_path}: hooks must be an object")

    hook_script = Path(hook_script)
    command = _command(Path(python_exe), hook_script)
    added = []
    for event in EVENTS:
        groups = hooks.setdefault(event, [])
        if not isinstance(groups, list):
            raise ValueError(f"{settings_path}: hooks.{event} must be an array")
        existing_handler = None
        for group in groups:
            if not isinstance(group, dict):
                continue
            handlers = group.get("hooks") or []
            if not isinstance(handlers, list):
                continue
            for handler in handlers:
                if isinstance(handler, dict) and (
                    handler.get("statusMessage") == f"IDP Codex monitor: {hook_script.as_posix()}"
                    or hook_script.as_posix() in str(handler.get("command", "")).replace("\\", "/")
                ):
                    existing_handler = handler
                    break
            if existing_handler:
                break
        if existing_handler is None:
            groups.append(
                {
                    "hooks": [
                        {
                            "type": "command",
                            "command": command,
                            "timeout": 5,
                            "statusMessage": f"IDP Codex monitor: {hook_script.as_posix()}",
                        }
                    ]
                }
            )
            added.append(event)
        elif existing_handler.get("command") != command:
            existing_handler["command"] = command
            existing_handler["timeout"] = 5
            existing_handler["statusMessage"] = f"IDP Codex monitor: {hook_script.as_posix()}"
            added.append(event)

    if added:
        settings_path.parent.mkdir(parents=True, exist_ok=True)
        _atomic_write(settings_path, data)
    return added


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Install Codex status hooks for the desktop pet")
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
        print(f"Installed Codex status hooks: {args.settings}")
        print(f"Added or updated events: {', '.join(added)}")
        print("Review and trust the hooks in Codex, then restart Codex.")
    else:
        print(f"Codex status hooks already installed: {args.settings}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
