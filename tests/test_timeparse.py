"""时间规整测试：固定「当前时间」验证「今天/明天/后天 + 时刻」→ ISO 的换算。"""

from datetime import datetime

from pet.timeparse import normalize_datetime

FIXED_NOW = datetime(2026, 10, 12, 9, 0, 0)


def test_iso_passthrough():
    assert normalize_datetime("2026-10-11T14:00") == "2026-10-11T14:00"


def test_natural_today():
    assert normalize_datetime("今天 14:30", now=lambda: FIXED_NOW) == "2026-10-12T14:30:00"


def test_natural_tomorrow():
    assert normalize_datetime("明天 09:05", now=lambda: FIXED_NOW) == "2026-10-13T09:05:00"


def test_natural_day_after_tomorrow():
    assert normalize_datetime("后天 18:00", now=lambda: FIXED_NOW) == "2026-10-14T18:00:00"


def test_unrecognized_passthrough():
    assert normalize_datetime("下午三点") == "下午三点"


def test_none_passthrough():
    assert normalize_datetime(None) is None
