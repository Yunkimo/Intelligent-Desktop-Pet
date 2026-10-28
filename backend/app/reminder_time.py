"""提醒时间的兼容解析与 UTC 规范化。"""

from datetime import datetime, timedelta, timezone

from . import config


def normalize_reminder_time(value: str) -> str:
    """接受 ISO 日期时间；旧无时区格式按配置偏移解释，始终输出 UTC。"""
    if not isinstance(value, str) or "T" not in value:
        raise ValueError("remind_at 必须是含 T 的 ISO 日期时间")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(
                tzinfo=timezone(timedelta(minutes=config.REMINDER_NAIVE_OFFSET_MINUTES))
            )
        return parsed.astimezone(timezone.utc).isoformat(timespec="microseconds")
    except (ValueError, OverflowError) as exc:
        raise ValueError("remind_at 必须是有效 ISO 日期时间") from exc


def utc_text(timestamp: float) -> str:
    """将时间戳转换为带 UTC 时区的稳定文本。"""
    return datetime.fromtimestamp(timestamp, timezone.utc).isoformat(timespec="microseconds")
