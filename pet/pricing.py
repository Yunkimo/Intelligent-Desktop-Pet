"""DeepSeek 价目表与费用估算（元 / 百万 token）。

价格来源：https://api-docs.deepseek.com/zh-cn/quick_start/pricing
抓取日期：2026-10-24。官方保留调价权利，变更后需手动更新下表。

高峰时段为北京时间周一至周五 09:00-12:00、14:00-18:00（不含中国法定节假日），
其余时段为空闲；空闲价恒为高峰价的一半，因此表里只存高峰价。节假日与调休未建模：
节假日按高峰计价（高估），调休上班的周末按空闲计价（低估），窗口中如实标注。
"""

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal

CN_TZ = timezone(timedelta(hours=8))
PRICE_AS_OF = date(2026, 10, 24)

_PEAK_MORNING = (time(9, 0), time(12, 0))
_PEAK_AFTERNOON = (time(14, 0), time(18, 0))
_OFF_PEAK_FACTOR = Decimal("0.5")
_PER_MILLION = Decimal(1_000_000)


@dataclass(frozen=True)
class ModelPrice:
    """单模型的高峰价：缓存命中输入、缓存未命中输入、输出，元每百万 token。"""

    cache_hit: Decimal
    cache_miss: Decimal
    output: Decimal


PRICES: dict[str, ModelPrice] = {
    "deepseek-flash": ModelPrice(Decimal("0.04"), Decimal("2"), Decimal("8")),
    "deepseek-v4-pro": ModelPrice(Decimal("0.30"), Decimal("9"), Decimal("27")),
}

# 官方仍接受的旧名，实际由对应现役模型提供服务并按该模型计费
ALIASES = {
    "deepseek-chat": "deepseek-flash",
    "deepseek-v4-flash": "deepseek-flash",
    "deepseek-v4-flash-vision-exp": "deepseek-flash",
}


def to_cn(when: datetime) -> datetime:
    """统一到北京时间；不带时区的时间按北京时间理解。"""
    return when.replace(tzinfo=CN_TZ) if when.tzinfo is None else when.astimezone(CN_TZ)


def is_peak(when: datetime) -> bool:
    """是否落在高峰时段。法定节假日未建模，节假日一律按高峰计。"""
    local = to_cn(when)
    if local.weekday() >= 5:
        return False
    clock = local.time()
    for start, end in (_PEAK_MORNING, _PEAK_AFTERNOON):
        if start <= clock < end:
            return True
    return False


def model_prices(model: str) -> ModelPrice | None:
    """按模型名取价目；别名归一到现役模型，未收录返回 None。"""
    return PRICES.get(ALIASES.get(model, model))


def estimate_cost_cny(
    model: str,
    prompt_tokens: int,
    cached_tokens: int,
    completion_tokens: int,
    when: datetime,
) -> Decimal | None:
    """估算单次调用费用；模型未收录时返回 None（token 仍照常记账）。"""
    price = model_prices(model)
    if price is None:
        return None
    cached = max(0, min(cached_tokens, prompt_tokens))
    uncached = prompt_tokens - cached
    cost = price.cache_hit * cached + price.cache_miss * uncached + price.output * completion_tokens
    if not is_peak(when):
        cost *= _OFF_PEAK_FACTOR
    return cost / _PER_MILLION
