"""微信登录和按提醒授权；身份来自服务端会话，不接受调用者指定 openid。"""

import asyncio
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, Field

from .. import config, wechat_store
from ..auth import require_token
from ..wechat_client import WeChatError, require_config

router = APIRouter(prefix="/api/wechat", tags=["wechat"], dependencies=[Depends(require_token)])


class LoginIn(BaseModel):
    """微信临时 code，禁止携带伪造的用户字段。"""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    code: str = Field(min_length=1, max_length=256)


class SubscribeIn(BaseModel):
    """request_id 对一次登记幂等；一个提醒事件最多产生一次成功推送。"""

    model_config = ConfigDict(extra="forbid")
    reminder_id: int = Field(gt=0)
    request_id: UUID
    template_id: str = Field(min_length=1, max_length=256)
    result: Literal["accept", "reject", "ban", "filter"]


def check_config(subscription: bool = False) -> None:
    """返回明确配置错误，不输出配置值。"""
    try:
        require_config(subscription=subscription)
    except WeChatError as exc:
        raise HTTPException(status_code=503, detail=exc.reason) from None


def current_user(authorization: str = Header(default="")) -> int:
    """校验 Bearer 会话，拒绝把 openid 或 API Key 当作用户会话。"""
    check_config()
    scheme, _, token = authorization.partition(" ")
    user_id = wechat_store.session_user(token) if scheme.lower() == "bearer" else None
    if user_id is None:
        raise HTTPException(status_code=401, detail="wechat_session_invalid")
    return user_id


@router.post("/login")
async def login(payload: LoginIn, request: Request, response: Response) -> dict:
    """兑换身份并签发本地会话；不向客户端返回微信 session_key/access_token。"""
    check_config()
    try:
        openid = await request.app.state.wechat_client.login(payload.code)
    except WeChatError as exc:
        status = 401 if exc.reason == "wechat_invalid_code" else 502
        raise HTTPException(status_code=status, detail=exc.reason) from None
    response.headers["Cache-Control"] = "no-store"
    return await asyncio.to_thread(wechat_store.new_session, openid)


@router.post("/subscribe")
def subscribe(payload: SubscribeIn, user_id: int = Depends(current_user)) -> dict:
    """登记用户报告的授权结果；真正发送权限由微信平台最终判定。"""
    check_config(subscription=True)
    if payload.template_id != config.WX_TEMPLATE_ID:
        raise HTTPException(status_code=422, detail="wechat_template_mismatch")
    try:
        return wechat_store.subscribe(
            user_id,
            payload.reminder_id,
            str(payload.request_id),
            payload.template_id,
            payload.result,
        )
    except wechat_store.SubscriptionError as exc:
        status = 404 if str(exc) == "reminder_not_found" else 409
        raise HTTPException(status_code=status, detail=str(exc)) from None


@router.get("/subscriptions/{reminder_id}")
def subscription_status(reminder_id: int, user_id: int = Depends(current_user)) -> list[dict]:
    """仅提供本人订阅记录，不暴露 openid、会话或上游响应。"""
    return wechat_store.status(reminder_id, user_id)
