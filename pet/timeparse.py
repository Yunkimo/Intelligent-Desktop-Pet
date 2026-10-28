"""自然语言时间规整：把「今天/明天/后天 HH:MM」等口语时间转成 ISO，供日程/提醒工具使用。

LLM 在 function calling 里应直接给出 ISO 时间，但偶尔会输出「明天 14:00」这类
口语写法；这里做一层兜底规整，识别不出则原样透传，交给后端自行校验。
"""

import re
from datetime import datetime, timedelta
from typing import Callable

_DAY_OFFSETS = {"今天": 0, "明天": 1, "后天": 2}
_TIME_RE = re.compile(r"^(今天|明天|后天)\s*(\d{1,2}):(\d{2})$")


def normalize_datetime(
    value: str | None,
    now: Callable[[], datetime] = datetime.now,
) -> str | None:
    """把「今天/明天/后天 HH:MM」规整为 ISO 字符串；其它输入（含 ISO）原样返回。

    now 可注入以便测试（默认取本机当前时间）。
    """
    if not value:
        return value
    value = value.strip()
    m = _TIME_RE.match(value)
    if not m:
        return value
    day_word, hour, minute = m.group(1), int(m.group(2)), int(m.group(3))
    base = now() + timedelta(days=_DAY_OFFSETS[day_word])
    return base.replace(hour=hour, minute=minute, second=0, microsecond=0).isoformat()
