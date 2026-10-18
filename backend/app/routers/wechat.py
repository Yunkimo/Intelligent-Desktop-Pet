"""微信登录和按提醒授权；身份来自服务端会话，不接受调用者指定 openid。"""

import asyncio
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, Field

from .. import config, db, wechat_store
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
    event_id: str | None = Field(default=None, min_length=1, max_length=128)


def current_user(authorization: str = Header(default="")) -> int:
    """校验 Bearer 会话，拒绝把 openid 或 API Key 当作用户会话。"""
    check_config()
    scheme, _, token = authorization.partition(" ")
    user_id = wechat_store.session_user(token) if scheme.lower() == "bearer" else None
    if user_id is None:
        raise HTTPException(status_code=401, detail="wechat_session_invalid")
    return user_id


class TaskReminderIn(BaseModel):
    """从服务端最新日程创建本人的手机提醒，不接收客户端指定身份。"""

    model_config = ConfigDict(extra="forbid")
    task_id: int = Field(gt=0)


@router.post("/reminders")
def ensure_task_reminder(payload: TaskReminderIn, user_id: int = Depends(current_user)) -> dict:
    """事务内查找或创建；同任务并发及响应丢失重放复用同一提醒。"""
    try:
        return db.ensure_phone_reminder(payload.task_id, user_id)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from None


@router.get("/reminders/{reminder_id}")
def reminder_detail(reminder_id: int, user_id: int = Depends(current_user)) -> dict:
    """消息落地页只读取当前会话拥有的提醒及最新日程。"""
    with db._conn() as conn:
        row = conn.execute(
            "SELECT r.*,d.event_id FROM reminders r JOIN reminder_deliveries d "
            "ON d.reminder_id=r.id WHERE r.id=? AND r.wechat_user_id=?",
            (reminder_id, user_id),
        ).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="reminder_not_found")
        task = conn.execute("SELECT * FROM tasks WHERE id=?", (row["task_id"],)).fetchone()
    return {"reminder": dict(row), "task": dict(task) if task else None}


@router.get("/reminders")
def list_owned_reminders(user_id: int = Depends(current_user)) -> list[dict]:
    """返回本人当前事件状态供页面恢复读取，不把历史 sent 当作新事件状态。"""
    with db._conn() as conn:
        rows = conn.execute(
            "SELECT r.id,r.task_id,r.remind_at,d.event_id,s.status FROM reminders r "
            "JOIN reminder_deliveries d ON d.reminder_id=r.id "
            "LEFT JOIN wechat_subscriptions s ON s.reminder_id=r.id AND s.event_id=d.event_id "
            "AND s.user_id=r.wechat_user_id WHERE r.wechat_user_id=? AND r.channel='phone'",
            (user_id,),
        ).fetchall()
    return [dict(row) for row in rows]


def check_config(subscription: bool = False) -> None:
    """返回明确配置错误，不输出配置值。"""
    try:
        require_config(subscription=subscription)
    except WeChatError as exc:
        raise HTTPException(status_code=503, detail=exc.reason) from None


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
            payload.event_id,
        )
    except wechat_store.SubscriptionError as exc:
        status = 404 if str(exc) == "reminder_not_found" else 409
        raise HTTPException(status_code=status, detail=str(exc)) from None


@router.get("/subscriptions/{reminder_id}")
def subscription_status(reminder_id: int, user_id: int = Depends(current_user)) -> list[dict]:
    """仅提供本人订阅记录，不暴露 openid、会话或上游响应。"""
    return wechat_store.status(reminder_id, user_id)
