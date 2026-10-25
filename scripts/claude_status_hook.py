"""Claude Code hook：把回合状态写入桌宠可读取的 JSON 文件。

在 Claude Code 的 hooks 配置里分别挂到：
- UserPromptSubmit → working（开始处理）
- PreToolUse / PostToolUse → working（工具执行期间；确认权限后恢复）
- Notification     → waiting（仅权限请求；空闲提醒忽略）
- Stop             → done（本轮完成）
- SessionStart / SessionEnd → idle

脚本只写状态，不输出任何内容，并始终以 0 退出，避免阻塞或改变 Claude
Code 的回合流程。状态文件路径可用 IDP_AGENT_STATUS_FILE 覆盖。
"""

import json
import os
import sys
import tempfile
import time
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DEFAULT_STATUS_PATH = BASE_DIR / "data" / "agent-status.json"

_EVENT_STATES = {
    "UserPromptSubmit": "working",
    "PreToolUse": "working",
    "PostToolUse": "working",
    "Stop": "done",
    "SessionStart": "idle",
    "SessionEnd": "idle",
}

# Notification 同时用于「请求权限」和「输入框空闲 60 秒」等提醒，
# 后者不能覆盖已完成的 done 状态，因此按 notification_type / 文案区分。
_PERMISSION_TYPES = {
    "permission_prompt",
    "worker_permission_prompt",
    "agent_needs_input",
    "elicitation_dialog",
    "elicitation_url_dialog",
    # 兼容旧版/社区字段命名
    "permission_request",
    "permission",
    "tool_permission",
}
_IDLE_TYPES = {"idle_prompt", "idle", "prompt_idle"}
_IGNORED_TYPES = {
    "auth_success",
    "elicitation_complete",
    "elicitation_response",
    "agent_completed",
}
_PERMISSION_HINTS = ("permission", "approve", "allow", "权限", "确认", "允许")
_IDLE_HINTS = ("waiting for your input", "idle", "空闲", "等待输入")


def _read_payload() -> dict:
    """读取 Claude Code 通过 stdin 传入的 JSON；无效输入按空字典处理。"""
    try:
        raw = sys.stdin.buffer.read()
        if not raw.strip():
            return {}
        data = json.loads(raw.decode("utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _state_for(payload: dict) -> str | None:
    """把 hook 事件映射为桌宠状态；非权限类 Notification 返回 None。"""
    event = payload.get("hook_event_name") or ""
    if event != "Notification":
        return _EVENT_STATES.get(event)

    ntype = str(payload.get("notification_type") or "").lower()
    if ntype.startswith("quota_auto_resume_"):
        return None
    if ntype in _PERMISSION_TYPES:
        return "waiting"
    if ntype in _IDLE_TYPES:
        return None
    if ntype in _IGNORED_TYPES:
        return None

    text = f"{payload.get('title') or ''} {payload.get('message') or ''}".lower()
    if any(hint in text for hint in _PERMISSION_HINTS):
        return "waiting"
    if any(hint in text for hint in _IDLE_HINTS):
        return None
    # 没有可识别文案时按权限请求处理，避免漏掉确认提醒
    return "waiting"


def _write_status(path: Path, payload: dict) -> None:
    """原子写入状态文件，避免桌宠读到半截 JSON。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    data = {
        "state": payload["state"],
        "event": payload["event"],
        "session_id": payload.get("session_id", ""),
        "ts": time.time(),
    }
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".agent-status-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)
        os.replace(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass


def main() -> int:
    try:
        payload = _read_payload()
        event = payload.get("hook_event_name") or ""
        state = _state_for(payload)
        # 也允许手动执行时用参数指定状态，便于本地验证
        if state is None and len(sys.argv) > 1 and sys.argv[1] in _EVENT_STATES.values():
            state = sys.argv[1]
            event = event or "manual"
        if state is None:
            return 0
        status_path = Path(os.environ.get("IDP_AGENT_STATUS_FILE", DEFAULT_STATUS_PATH))
        _write_status(
            status_path,
            {"state": state, "event": event, "session_id": payload.get("session_id", "")},
        )
    except Exception:
        # 通知失败不应影响 Claude Code 本身
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
