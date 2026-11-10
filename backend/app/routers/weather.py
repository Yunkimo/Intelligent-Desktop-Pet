"""小程序天气横幅数据；认证用户可查询，不消耗微信授权。"""

from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request, Response

from ..auth import current_user
from .web_query import checked

router = APIRouter(
    prefix="/api/weather", tags=["weather-tips"], dependencies=[Depends(current_user)]
)


@router.get("/tomorrow")
async def tomorrow(
    request: Request, response: Response, city: Annotated[str, Query(min_length=1, max_length=80)]
):
    response.headers["Cache-Control"] = "no-store"
    return await request.app.state.weather_tips.tomorrow(checked(city, city=True))
