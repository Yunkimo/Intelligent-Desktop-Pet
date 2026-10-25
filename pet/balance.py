"""账户余额查询：只对接有官方余额接口的服务商，拿不到就如实报错。

DeepSeek：GET {root}/user/balance，与推理共用同一把 API key。
Moonshot：GET {root}/v1/users/me/balance。
其余 OpenAI 兼容服务商没有可用模型 key 直接查询的余额接口，不做猜测。

注意：余额是**账户级**数据，无法按 key 或项目拆分，与本地记账口径不同。
"""

from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from urllib.parse import urlsplit

import httpx

DEFAULT_TIMEOUT_SECONDS = 5.0

# 已核实服务商的控制台用量页；未收录的按接口地址推出站点根
CONSOLE_URLS: tuple[tuple[str, str], ...] = (
    ("deepseek.com", "https://platform.deepseek.com/usage"),
)


class BalanceError(Exception):
    """余额查询失败；消息可直接展示给用户，且绝不包含 key。"""


@dataclass(frozen=True)
class BalanceTarget:
    """一次查询的目标；api_key 不进入 repr，避免对象被打印时泄漏。"""

    api_key: str = field(repr=False)
    base_url: str


@dataclass(frozen=True)
class Balance:
    """归一化后的余额；金额字段用 Decimal，原样保留服务商给的小数位。"""

    provider: str
    currency: str
    total: Decimal
    granted: Decimal | None
    topped_up: Decimal | None
    available: bool


def _endpoint(base_url: str) -> tuple[str, str]:
    """解析出 (服务商名, 余额接口地址)；只保留 scheme+host，忽略用户填的路径。"""
    raw = base_url.strip()
    parts = urlsplit(raw if "://" in raw else f"https://{raw}")
    host = (parts.hostname or "").lower()
    root = f"{parts.scheme or 'https'}://{parts.netloc}"
    if host.endswith("deepseek.com"):
        return "DeepSeek", f"{root}/user/balance"
    if "moonshot" in host:
        return "Moonshot", f"{root}/v1/users/me/balance"
    raise BalanceError("当前服务商未提供余额查询接口，仅显示本地用量记账")


def console_url(base_url: str) -> str:
    """服务商控制台的用量页，供「跳转至 API 网站」使用。

    已收录的服务商直接给控制台地址；未收录的退回接口站点根，至少不跳错站点。
    地址为空或无法解析时返回空串，由调用方决定提示还是禁用按钮。
    """
    raw = (base_url or "").strip()
    if not raw:
        return ""
    host = (urlsplit(raw if "://" in raw else f"https://{raw}").hostname or "").lower()
    for suffix, url in CONSOLE_URLS:
        if host == suffix or host.endswith("." + suffix):
            return url
    return website_url(raw)


def website_url(base_url: str) -> str:
    """由配置的接口地址推出服务商站点根（未收录服务商时的兜底）。

    只保留 scheme + host，用户填 `https://api.deepseek.com/v1` 也指向站点根；
    地址为空或无法解析时返回空串。
    """
    raw = (base_url or "").strip()
    if not raw:
        return ""
    parts = urlsplit(raw if "://" in raw else f"https://{raw}")
    if not parts.netloc:
        return ""
    return f"{parts.scheme or 'https'}://{parts.netloc}/"


def _decimal(value: object) -> Decimal | None:
    """宽松转金额；缺失或非法返回 None。"""
    if value is None or isinstance(value, bool):
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None


def _first_balance_info(data: object) -> dict:
    """取 balance_infos 里第一条（优先人民币），结构不对就报格式异常。"""
    if not isinstance(data, dict):
        raise BalanceError("余额查询返回格式异常")
    infos = data.get("balance_infos")
    if not isinstance(infos, list) or not infos:
        raise BalanceError("余额查询返回格式异常：缺少 balance_infos")
    chosen = next(
        (item for item in infos if isinstance(item, dict) and item.get("currency") == "CNY"),
        infos[0],
    )
    if not isinstance(chosen, dict):
        raise BalanceError("余额查询返回格式异常：balance_infos 条目无效")
    return chosen


def _parse_deepseek(data: object) -> Balance:
    info = _first_balance_info(data)
    total = _decimal(info.get("total_balance"))
    if total is None:
        raise BalanceError("余额查询返回格式异常：缺少 total_balance")
    available = data.get("is_available") if isinstance(data, dict) else None
    return Balance(
        provider="DeepSeek",
        currency=str(info.get("currency") or "CNY"),
        total=total,
        granted=_decimal(info.get("granted_balance")),
        topped_up=_decimal(info.get("topped_up_balance")),
        available=bool(available) if available is not None else True,
    )


def _parse_moonshot(data: object) -> Balance:
    payload = data.get("data") if isinstance(data, dict) else None
    if not isinstance(payload, dict):
        raise BalanceError("余额查询返回格式异常：缺少 data")
    total = _decimal(payload.get("available_balance"))
    if total is None:
        raise BalanceError("余额查询返回格式异常：缺少 available_balance")
    return Balance(
        provider="Moonshot",
        currency="CNY",
        total=total,
        granted=_decimal(payload.get("voucher_balance")),
        topped_up=_decimal(payload.get("cash_balance")),
        available=total > 0,
    )


def fetch_balance(
    target: BalanceTarget,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
    transport: httpx.BaseTransport | None = None,
) -> Balance:
    """查询账户余额；任何失败都以 BalanceError 抛出可读文案。

    transport 仅供测试注入 MockTransport，生产调用留空。
    """
    provider, url = _endpoint(target.base_url)
    if not target.api_key:
        raise BalanceError("未配置账户 key，请在 .env 设置 ACCOUNT_API_KEY")
    try:
        with httpx.Client(timeout=timeout, follow_redirects=False, transport=transport) as client:
            response = client.get(url, headers={"Authorization": f"Bearer {target.api_key}"})
    except httpx.TimeoutException as exc:
        raise BalanceError("余额查询超时，请检查网络后重试") from exc
    except httpx.HTTPError as exc:
        raise BalanceError("余额查询失败：网络不可用") from exc

    if response.status_code == 401:
        raise BalanceError("账户验证失败，请检查 ACCOUNT_API_KEY 是否正确")
    if response.status_code != 200:
        raise BalanceError(f"余额查询失败：HTTP {response.status_code}")
    try:
        data = response.json()
    except ValueError as exc:
        raise BalanceError("余额查询返回格式异常：不是合法 JSON") from exc
    return _parse_deepseek(data) if provider == "DeepSeek" else _parse_moonshot(data)
