"""微信 HTTP 适配器：固定官方主机、有限超时、进程内凭证缓存。"""

import asyncio
import math
import time
from collections.abc import Callable
from datetime import datetime, timedelta, timezone

import httpx

from . import config


class WeChatError(Exception):
    """仅暴露脱敏错误类别，不保存上游响应或带凭证的 URL。"""

    def __init__(self, reason: str, *, uncertain: bool = False, retryable: bool = False) -> None:
        super().__init__(reason)
        self.reason = reason
        self.uncertain = uncertain
        self.retryable = retryable


def require_config(*, subscription: bool = False) -> None:
    """缺失配置时明确拒绝微信功能，不影响其他渠道。"""
    if not config.WX_ENABLED or not config.WX_APPID or not config.WX_SECRET:
        raise WeChatError("wechat_not_configured")
    if subscription and (not config.WX_TEMPLATE_ID or not config.WX_TEMPLATE_FIELDS):
        raise WeChatError("wechat_template_not_configured")


class WeChatClient:
    """每个应用实例一个客户端；transport/clock 可注入以隔离真实微信。"""

    def __init__(
        self, transport: httpx.AsyncBaseTransport | None = None, clock: Callable = time.monotonic
    ) -> None:
        self._transport = transport
        self._http: httpx.AsyncClient | None = None
        self._clock = clock
        self._token = ""
        self._expires_at = 0.0
        self._token_lock = asyncio.Lock()

    async def close(self) -> None:
        """释放连接，并从实例清除缓存凭证。"""
        self._token = ""
        if self._http is not None:
            await self._http.aclose()

    async def _request(self, method: str, path: str, *, sending: bool = False, **kwargs) -> dict:
        if self._http is None:
            self._http = httpx.AsyncClient(
                base_url="https://api.weixin.qq.com",
                timeout=config.WX_TIMEOUT_SECONDS,
                follow_redirects=False,
                transport=self._transport,
            )
        try:
            response = await asyncio.wait_for(
                self._http.request(method, path, **kwargs), config.WX_TIMEOUT_SECONDS
            )
        except (asyncio.TimeoutError, httpx.RequestError):
            raise WeChatError(
                "wechat_transport_error", uncertain=sending, retryable=not sending
            ) from None
        if response.status_code != 200:
            raise WeChatError("wechat_http_error", uncertain=sending, retryable=not sending)
        try:
            data = response.json()
        except ValueError:
            raise WeChatError("wechat_invalid_response", uncertain=sending) from None
        if not isinstance(data, dict):
            raise WeChatError("wechat_invalid_response", uncertain=sending)
        return data

    async def login(self, code: str) -> str:
        """兑换临时登录 code，只使用 openid，丢弃 session_key。"""
        require_config()
        data = await self._request(
            "GET",
            "/sns/jscode2session",
            params={
                "appid": config.WX_APPID,
                "secret": config.WX_SECRET,
                "js_code": code,
                "grant_type": "authorization_code",
            },
        )
        error = data.get("errcode", 0)
        if type(error) is not int:
            raise WeChatError("wechat_invalid_response")
        if error != 0:
            if error in {40029, 40163}:
                raise WeChatError("wechat_invalid_code")
            raise WeChatError("wechat_login_failed")
        openid = data.get("openid")
        if not isinstance(openid, str) or not openid.strip() or len(openid) > 128:
            raise WeChatError("wechat_invalid_response")
        return openid

    async def access_token(self, rejected_token: str | None = None) -> str:
        """并发刷新合并为一次；拒绝的旧 token 不会清除刚刷新出的新 token。"""
        require_config()
        async with self._token_lock:
            if self._token and self._clock() < self._expires_at and self._token != rejected_token:
                return self._token
            self._token = ""
            data = await self._request(
                "GET",
                "/cgi-bin/token",
                params={
                    "grant_type": "client_credential",
                    "appid": config.WX_APPID,
                    "secret": config.WX_SECRET,
                },
            )
            token, lifetime = data.get("access_token"), data.get("expires_in")
            error = data.get("errcode", 0)
            if type(error) is not int:
                raise WeChatError("wechat_invalid_response")
            if error != 0:
                raise WeChatError("wechat_token_failed", retryable=error == -1)
            if (
                not isinstance(token, str)
                or not token
                or type(lifetime) not in {int, float}
                or not math.isfinite(lifetime)
                or lifetime <= 0
            ):
                raise WeChatError("wechat_invalid_response")
            self._token = token
            self._expires_at = self._clock() + lifetime - min(60, lifetime * 0.1)
            return token

    async def send(self, openid: str, reminder: dict) -> None:
        """仅在微信明确拒绝过期 token 时重试一次；发送结果不明时禁止自动重发。"""
        require_config(subscription=True)
        fields = {}
        for key, source in config.WX_TEMPLATE_FIELDS.items():
            if source == "remind_at":
                local = datetime.fromisoformat(reminder[source]).astimezone(
                    timezone(timedelta(minutes=config.REMINDER_NAIVE_OFFSET_MINUTES))
                )
                value = local.strftime("%Y-%m-%d %H:%M")
            else:
                value = str(reminder.get(source) or reminder["title"])[:20]
            fields[key] = {"value": value}
        payload = {
            "touser": openid,
            "template_id": config.WX_TEMPLATE_ID,
            "data": fields,
            "miniprogram_state": config.WX_MINIPROGRAM_STATE,
            "lang": "zh_CN",
        }
        token = await self.access_token()
        for attempt in range(2):
            data = await self._request(
                "POST",
                "/cgi-bin/message/subscribe/send",
                sending=True,
                params={"access_token": token},
                json=payload,
            )
            error = data.get("errcode")
            if type(error) is not int:
                raise WeChatError("wechat_invalid_response", uncertain=True)
            if error == 0:
                return
            if error in {40001, 40014, 42001} and attempt == 0:
                token = await self.access_token(rejected_token=token)
                continue
            reasons = {
                43101: "wechat_no_subscription",
                40003: "wechat_invalid_recipient",
                40037: "wechat_invalid_template",
                47003: "wechat_invalid_fields",
                41030: "wechat_invalid_page",
                45009: "wechat_rate_limited",
            }
            raise WeChatError(reasons.get(error, "wechat_send_rejected"))
