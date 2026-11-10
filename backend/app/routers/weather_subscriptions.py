"""天气订阅只接受微信会话，不使用共享 API Key 或客户端 openid。"""

from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, ConfigDict, Field

from .. import config
from .. import weather_subscriptions as store
from ..auth import current_wechat_user
from ..wechat_client import WeChatError, require_config
from .web_query import checked

router = APIRouter(prefix="/api/weather/subscriptions", tags=["weather-subscriptions"])


class PrepareIn(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    city: str = Field(default="长沙", min_length=1, max_length=80)


class RegisterIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request_id: UUID
    template_id: str = Field(min_length=1, max_length=256)
    result: Literal["accept", "reject", "ban", "filter"]


def configured() -> None:
    try:
        require_config()
    except WeChatError as exc:
        raise HTTPException(503, exc.reason) from None
    if not config.WEATHER_WX_TEMPLATE_ID or not config.WEATHER_WX_TEMPLATE_FIELDS:
        raise HTTPException(503, "weather_template_not_configured")


def invoke(function, *args):
    try:
        return function(*args)
    except store.WeatherSubscriptionError as exc:
        raise HTTPException(
            404 if str(exc) == "weather_event_not_found" else 409, str(exc)
        ) from None


@router.post("", status_code=201)
def prepare(payload: PrepareIn, response: Response, user: int = Depends(current_wechat_user)):
    configured()
    response.headers["Cache-Control"] = "no-store"
    return invoke(store.prepare, user, checked(payload.city, city=True))


@router.get("")
def list_events(response: Response, user: int = Depends(current_wechat_user)):
    response.headers["Cache-Control"] = "no-store"
    return store.list_owned(user)


@router.get("/{event_id}")
def detail(event_id: UUID, response: Response, user: int = Depends(current_wechat_user)):
    response.headers["Cache-Control"] = "no-store"
    return invoke(store.detail, user, str(event_id))


@router.post("/{event_id}/authorization")
def register(
    event_id: UUID,
    payload: RegisterIn,
    response: Response,
    user: int = Depends(current_wechat_user),
):
    configured()
    response.headers["Cache-Control"] = "no-store"
    return invoke(
        store.register,
        user,
        str(event_id),
        str(payload.request_id),
        payload.template_id,
        payload.result,
    )


@router.delete("/{event_id}")
def cancel(event_id: UUID, user: int = Depends(current_wechat_user)):
    return invoke(store.cancel, user, str(event_id))
