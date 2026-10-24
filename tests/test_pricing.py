"""价目表与费用估算测试：时段边界、别名归一、未收录模型。"""

from datetime import datetime, timezone
from decimal import Decimal

from pet.pricing import (
    ALIASES,
    PRICES,
    estimate_cost_cny,
    is_peak,
    model_prices,
)

# 2026-10-26 是周一，2026-10-24 是周六
MONDAY = (2026, 10, 26)
SATURDAY = (2026, 10, 24)


def _at(hour: int, minute: int = 0, day=MONDAY) -> datetime:
    return datetime(*day, hour, minute)


def test_peak_boundaries_are_half_open():
    assert is_peak(_at(8, 59)) is False
    assert is_peak(_at(9, 0)) is True
    assert is_peak(_at(11, 59)) is True
    assert is_peak(_at(12, 0)) is False
    assert is_peak(_at(13, 59)) is False
    assert is_peak(_at(14, 0)) is True
    assert is_peak(_at(17, 59)) is True
    assert is_peak(_at(18, 0)) is False


def test_weekend_is_off_peak():
    assert is_peak(_at(10, 0, SATURDAY)) is False


def test_naive_time_is_read_as_beijing_and_utc_is_converted():
    # 北京时间 09:00 = UTC 01:00，同一时刻两种写法结论必须一致
    assert is_peak(datetime(*MONDAY, 1, 0, tzinfo=timezone.utc)) is True
    assert is_peak(datetime(*MONDAY, 0, 59, tzinfo=timezone.utc)) is False


def test_holiday_is_treated_as_peak():
    """法定节假日未建模：国庆当天按工作日高峰计价（已知会高估，口径写进窗口）。"""
    assert is_peak(datetime(2026, 10, 1, 10, 0)) is True


def test_alias_maps_to_live_model():
    assert model_prices("deepseek-chat") is PRICES["deepseek-flash"]
    assert ALIASES["deepseek-chat"] == "deepseek-flash"
    assert model_prices("deepseek-v4-pro") is PRICES["deepseek-v4-pro"]


def test_unknown_model_has_no_price():
    assert model_prices("some-other-model") is None
    assert estimate_cost_cny("some-other-model", 1000, 0, 100, _at(10)) is None


def test_cost_uses_separate_cache_hit_and_miss_prices():
    # 高峰：命中 0.04、未命中 2、输出 8（元/百万）
    peak = estimate_cost_cny("deepseek-flash", 1_000_000, 400_000, 1_000_000, _at(10))
    assert peak == Decimal("9.216")
    # 空闲价恒为高峰价的一半
    idle = estimate_cost_cny("deepseek-flash", 1_000_000, 400_000, 1_000_000, _at(20))
    assert idle == Decimal("4.608")


def test_cached_tokens_are_clamped_to_prompt():
    """缓存命中数异常大于输入数时按输入数封顶，不会算出负的未命中量。"""
    odd = estimate_cost_cny("deepseek-flash", 1000, 5000, 0, _at(10))
    assert odd == Decimal(1000) * PRICES["deepseek-flash"].cache_hit / Decimal(1_000_000)
