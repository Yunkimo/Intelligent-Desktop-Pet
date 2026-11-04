"""生活习惯记忆：本地明文存储的长期偏好，与最近 N 轮对话历史分开。

只保存「稳定、可复用」的偏好（作息、饮食、学习习惯等），不保存对话原文。
新增/删除都落在 data/habits.json，用户可在「生活习惯」窗口查看与清空。
"""

import json
import os
import threading
from datetime import datetime
from pathlib import Path

MAX_TEXT_LENGTH = 80
DEFAULT_MAX_ITEMS = 50


def _normalize(text: str) -> str:
    """去空白、转小写，用于判重；不改变展示用原文。"""
    return "".join(text.split()).lower()


class HabitStore:
    """习惯列表的读写；写盘用临时文件 + 原子替换，避免半截 JSON。"""

    def __init__(self, path: Path, max_items: int = DEFAULT_MAX_ITEMS) -> None:
        self.path = Path(path)
        self.max_items = max(1, int(max_items))
        self.load_error: str | None = None
        self._lock = threading.Lock()
        self._habits: list[dict] = []
        self._next_id = 1
        self._load()

    # ---------- 对外接口 ----------
    def list_habits(self) -> list[dict]:
        """返回副本，避免调用方直接改内部列表。"""
        with self._lock:
            return [dict(item) for item in self._habits]

    def add(self, text: str) -> tuple[bool, str]:
        """新增一条习惯；重复或超长返回 (False, 原因)。"""
        cleaned = " ".join(str(text or "").split())
        if not cleaned:
            return False, "内容为空"
        if len(cleaned) > MAX_TEXT_LENGTH:
            return False, f"太长啦（最多 {MAX_TEXT_LENGTH} 字）"
        key = _normalize(cleaned)
        with self._lock:
            if any(_normalize(item["text"]) == key for item in self._habits):
                return False, "已经记过这条啦"
            if len(self._habits) >= self.max_items:
                return False, f"最多记住 {self.max_items} 条，先删几条吧"
            item = {
                "id": self._next_id,
                "text": cleaned,
                "created_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
            }
            self._habits.append(item)
            self._next_id += 1
            self._save_locked()
        return True, cleaned

    def remove(self, habit_id: int) -> bool:
        """按 id 删除一条；不存在返回 False。"""
        with self._lock:
            before = len(self._habits)
            self._habits = [item for item in self._habits if item["id"] != habit_id]
            if len(self._habits) == before:
                return False
            self._save_locked()
        return True

    def forget(self, keyword: str) -> int:
        """按关键词模糊删除，返回删除条数（供工具调用）。"""
        needle = _normalize(keyword)
        if not needle:
            return 0
        with self._lock:
            keep = [item for item in self._habits if needle not in _normalize(item["text"])]
            removed = len(self._habits) - len(keep)
            if removed:
                self._habits = keep
                self._save_locked()
        return removed

    def clear(self) -> int:
        """清空全部习惯，返回删除条数。"""
        with self._lock:
            count = len(self._habits)
            if count:
                self._habits = []
                self._save_locked()
        return count

    def summary(self, limit: int = 8) -> str:
        """给系统提示词用的紧凑摘要；没有习惯时返回空串。"""
        with self._lock:
            items = [item["text"] for item in self._habits[-limit:]]
        if not items:
            return ""
        return "主人长期的生活习惯（供你参考，不要逐条复述）：\n" + "\n".join(
            f"- {text}" for text in items
        )

    # ---------- 内部 ----------
    def _load(self) -> None:
        if not self.path.exists():
            return
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            self.load_error = f"习惯记录无法读取，已从空开始：{exc}"
            return
        items = data.get("habits") if isinstance(data, dict) else None
        if not isinstance(items, list):
            return
        habits = []
        for raw in items:
            if not isinstance(raw, dict):
                continue
            text = str(raw.get("text") or "").strip()
            if not text:
                continue
            habits.append(
                {
                    "id": int(raw.get("id") or len(habits) + 1),
                    "text": text[:MAX_TEXT_LENGTH],
                    "created_at": str(raw.get("created_at") or ""),
                }
            )
        self._habits = habits[: self.max_items]
        self._next_id = max((item["id"] for item in self._habits), default=0) + 1

    def _save_locked(self) -> None:
        payload = {
            "version": 1,
            "habits": self._habits,
        }
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
            os.replace(tmp, self.path)
        except OSError:
            # 文件被占用时保留内存数据，下次再试
            pass
