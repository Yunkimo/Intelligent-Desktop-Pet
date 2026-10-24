"""账户余额查询测试：地址归一、服务商支持范围、错误映射与密钥不外泄。"""

from decimal import Decimal

import httpx
import pytest

from pet.balance import BalanceError, BalanceTarget, _endpoint, fetch_balance

_KEY = "sk-secret-should-not-leak"


def _client(handler, body=None, status_code: int = 200):
    """构造 MockTransport：记录请求，按需返回固定响应。"""

    def responder(request: httpx.Request) -> httpx.Response:
        if handler is not None:
            return handler(request)
        return httpx.Response(status_code, json=body)

    return httpx.MockTransport(responder)


def _target(base_url: str = "https://api.deepseek.com", key: str = _KEY) -> BalanceTarget:
    return BalanceTarget(api_key=key, base_url=base_url)


# ---------- 地址归一 ----------
def test_endpoint_accepts_base_with_or_without_v1():
    assert _endpoint("https://api.deepseek.com") == (
        "DeepSeek",
        "https://api.deepseek.com/user/balance",
    )
    assert _endpoint("https://api.deepseek.com/v1") == (
        "DeepSeek",
        "https://api.deepseek.com/user/balance",
    )


def test_endpoint_handles_missing_scheme_and_port():
    provider, url = _endpoint("api.deepseek.com:8443")
    assert provider == "DeepSeek"
    assert url == "https://api.deepseek.com:8443/user/balance"


def test_endpoint_supports_moonshot():
    assert _endpoint("https://api.moonshot.cn/v1") == (
        "Moonshot",
        "https://api.moonshot.cn/v1/users/me/balance",
    )


def test_unsupported_provider_raises_without_network():
    def boom(_request):  # pragma: no cover - 不应被调用
        raise AssertionError("不支持的服务商不应发起请求")

    with pytest.raises(BalanceError) as excinfo:
        fetch_balance(_target("https://api.openai.com/v1"), transport=_client(boom))
    assert "未提供余额查询接口" in str(excinfo.value)


# ---------- 正常解析 ----------
def test_deepseek_balance_is_parsed():
    body = {
        "is_available": True,
        "balance_infos": [
            {"currency": "USD", "total_balance": "1.00", "granted_balance": "0"},
            {
                "currency": "CNY",
                "total_balance": "110.00",
                "granted_balance": "10.00",
                "topped_up_balance": "100.00",
            },
        ],
    }
    balance = fetch_balance(_target(), transport=_client(None, body))

    assert balance.provider == "DeepSeek"
    assert balance.currency == "CNY"  # 多币种时优先人民币
    assert balance.total == Decimal("110.00")
    assert balance.granted == Decimal("10.00")
    assert balance.topped_up == Decimal("100.00")
    assert balance.available is True


def test_moonshot_balance_is_parsed():
    body = {"data": {"available_balance": 49.5, "voucher_balance": 46.5, "cash_balance": 3.0}}
    balance = fetch_balance(_target("https://api.moonshot.cn"), transport=_client(None, body))

    assert balance.provider == "Moonshot"
    assert balance.total == Decimal("49.5")
    assert balance.available is True


def test_request_carries_bearer_token():
    seen = {}

    def capture(request):
        seen["auth"] = request.headers.get("authorization")
        seen["url"] = str(request.url)
        return httpx.Response(
            200, json={"balance_infos": [{"currency": "CNY", "total_balance": "1"}]}
        )

    fetch_balance(_target(), transport=_client(capture))
    assert seen["auth"] == f"Bearer {_KEY}"
    assert seen["url"].endswith("/user/balance")


# ---------- 错误映射 ----------
def test_unauthorized_message_hides_key():
    with pytest.raises(BalanceError) as excinfo:
        fetch_balance(_target(), transport=_client(None, {}, status_code=401))
    message = str(excinfo.value)
    assert "验证失败" in message
    assert _KEY not in message


def test_server_error_reports_status_code():
    with pytest.raises(BalanceError) as excinfo:
        fetch_balance(_target(), transport=_client(None, {}, status_code=500))
    assert "HTTP 500" in str(excinfo.value)


def test_timeout_is_reported_as_readable_message():
    def timeout(_request):
        raise httpx.TimeoutException("timed out")

    with pytest.raises(BalanceError) as excinfo:
        fetch_balance(_target(), transport=_client(timeout))
    assert "超时" in str(excinfo.value)


def test_malformed_json_is_reported():
    def bad(_request):
        return httpx.Response(200, content=b"<html>not json</html>")

    with pytest.raises(BalanceError) as excinfo:
        fetch_balance(_target(), transport=_client(bad))
    assert "格式异常" in str(excinfo.value)


def test_missing_balance_infos_is_reported():
    with pytest.raises(BalanceError) as excinfo:
        fetch_balance(_target(), transport=_client(None, {"is_available": True}))
    assert "balance_infos" in str(excinfo.value)


def test_missing_key_is_rejected_before_request():
    with pytest.raises(BalanceError) as excinfo:
        fetch_balance(_target(key=""), transport=_client(None, {}))
    assert "ACCOUNT_API_KEY" in str(excinfo.value)


def test_target_repr_hides_key():
    assert _KEY not in repr(_target())
