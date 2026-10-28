"""Token 用量记账：归一化各服务商的 usage 字段，按天聚合后持久化。

记账口径：每次 LLM HTTP 调用记一条（工具循环里一轮就是一条），输入与输出 token 分别
累加。费用按**调用发起时**的价目与时段估算，仅供自查，不代表官方账单。未收录的模型
照常统计 token，但费用计 0 并单独累计 `unpriced`，由界面提示。
"""

import json
import os
import threading
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation
from pathlib import Path

from .pricing import estimate_cost_cny, to_cn

_VERSION = 1
_ZERO = Decimal("0")


@dataclass
class Totals:
    """一段统计口径内的累计量。cost_cny 用 Decimal，落盘时存字符串避免浮点漂移。"""

    prompt: int = 0
    completion: int = 0
    cached: int = 0
    requests: int = 0
    cost_cny: Decimal = _ZERO
    unpriced: int = 0

    @property
    def total_tokens(self) -> int:
        return self.prompt + self.completion

    def add(self, prompt: int, completion: int, cached: int, cost: Decimal | None) -> None:
        """累加一次调用；cost 为 None 表示模型未收录，只把 token 计入 unpriced。"""
        self.prompt += prompt
        self.completion += completion
        self.cached += cached
        self.requests += 1
        if cost is None:
            self.unpriced += prompt + completion
        else:
            self.cost_cny += cost

    def merge(self, other: "Totals") -> None:
        self.prompt += other.prompt
        self.completion += other.completion
        self.cached += other.cached
        self.requests += other.requests
        self.cost_cny += other.cost_cny
        self.unpriced += other.unpriced

    def copy(self) -> "Totals":
        return replace(self)

    def to_dict(self) -> dict:
        return {
            "prompt": self.prompt,
            "completion": self.completion,
            "cached": self.cached,
            "requests": self.requests,
            "cost_cny": str(self.cost_cny),
            "unpriced": self.unpriced,
        }

    @classmethod
    def from_dict(cls, data: object) -> "Totals":
        """从落盘数据还原；任何字段缺失或非法都按 0 处理，不抛异常。"""
        if not isinstance(data, dict):
            return cls()
        return cls(
            prompt=_as_int(data.get("prompt")) or 0,
            completion=_as_int(data.get("completion")) or 0,
            cached=_as_int(data.get("cached")) or 0,
            requests=_as_int(data.get("requests")) or 0,
            cost_cny=_as_decimal(data.get("cost_cny")),
            unpriced=_as_int(data.get("unpriced")) or 0,
        )


def _as_int(value: object) -> int | None:
    """宽松转整数：bool 与非数字返回 None，负数按 0。"""
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        return None
    try:
        return max(0, int(float(value)))
    except (TypeError, ValueError):
        return None


def _as_decimal(value: object) -> Decimal:
    """宽松转金额；非法值按 0 处理。"""
    if isinstance(value, bool):
        return _ZERO
    try:
        return max(_ZERO, Decimal(str(value)))
    except (InvalidOperation, TypeError, ValueError):
        return _ZERO


def normalize_usage(usage: object) -> tuple[int, int, int] | None:
    """把各服务商的 usage 归一成 (prompt, completion, cached)。

    缓存命中优先取 DeepSeek 的 prompt_cache_hit_tokens，其次取 OpenAI 标准的
    prompt_tokens_details.cached_tokens，两者都没有时按全部未命中的 0 处理。
    prompt_tokens 缺失说明这条 usage 不可用，返回 None 不记账。
    """
    if usage is None:
        return None
    prompt = _as_int(getattr(usage, "prompt_tokens", None))
    if prompt is None:
        return None
    completion = _as_int(getattr(usage, "completion_tokens", None)) or 0
    cached = _as_int(getattr(usage, "prompt_cache_hit_tokens", None))
    if cached is None:
        details = getattr(usage, "prompt_tokens_details", None)
        cached = _as_int(getattr(details, "cached_tokens", None))
    cached = 0 if cached is None else min(cached, prompt)
    return prompt, completion, cached


class UsageStore:
    """本地 token 记账：内存累计 + 按天明细，落盘为 usage.json。

    ChatWorker 在后台线程调用 record_usage，界面线程调用 snapshot，两者用同一把锁。
    写盘先写临时文件再原子替换，避免进程中断留下半截 JSON。
    """

    def __init__(self, path: Path, retention_days: int = 90) -> None:
        self.path = Path(path)
        self.retention_days = max(1, int(retention_days))
        self.load_error: str | None = None
        self._lock = threading.Lock()
        self._total = Totals()
        self._days: dict[str, Totals] = {}
        self._load()

    # ---------- 对外接口 ----------
    def record_usage(self, usage: object, model: str, *, at: datetime | None = None) -> None:
        """记录一次调用；usage 不可用时静默跳过，绝不影响对话主流程。"""
        parsed = normalize_usage(usage)
        if parsed is None:
            return
        prompt, completion, cached = parsed
        when = to_cn(at) if at is not None else datetime.now().astimezone()
        when = to_cn(when)
        cost = estimate_cost_cny(model, prompt, cached, completion, when)
        key = when.date().isoformat()
        with self._lock:
            self._total.add(prompt, completion, cached, cost)
            day = self._days.setdefault(key, Totals())
            day.add(prompt, completion, cached, cost)
            self._trim_locked(when.date())
            self._save_locked()

    def snapshot(self, now: datetime | None = None) -> dict:
        """返回今日 / 近 7 天 / 总计三段汇总，以及按天明细（新到旧）。"""
        current = to_cn(now) if now is not None else datetime.now().astimezone()
        current = to_cn(current)
        today_key = current.date().isoformat()
        week_keys = {(current.date() - timedelta(days=i)).isoformat() for i in range(7)}
        with self._lock:
            today = self._days.get(today_key, Totals()).copy()
            week = Totals()
            for key in week_keys:
                day = self._days.get(key)
                if day is not None:
                    week.merge(day)
            return {
                "today": today,
                "last_7_days": week,
                "total": self._total.copy(),
                "days": [(key, self._days[key].copy()) for key in sorted(self._days, reverse=True)],
                "load_error": self.load_error,
            }

    # ---------- 内部 ----------
    def _load(self) -> None:
        if not self.path.exists():
            return
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            self.load_error = f"用量记录无法读取，已从零开始：{exc}"
            return
        if not isinstance(raw, dict):
            self.load_error = "用量记录格式异常，已从零开始"
            return
        self._total = Totals.from_dict(raw.get("total"))
        days = raw.get("days")
        if isinstance(days, dict):
            self._days = {str(k): Totals.from_dict(v) for k, v in days.items()}

    def _trim_locked(self, today) -> None:
        """只裁按天明细，总计永不裁剪。"""
        cutoff = (today - timedelta(days=self.retention_days)).isoformat()
        for key in [k for k in self._days if k < cutoff]:
            del self._days[key]

    def _save_locked(self) -> None:
        payload = {
            "version": _VERSION,
            "total": self._total.to_dict(),
            "days": {key: value.to_dict() for key, value in self._days.items()},
        }
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
            os.replace(tmp, self.path)
        except OSError:
            # Windows 下文件可能被占用：保留内存里的数据，下次记录或退出时再试
            pass
