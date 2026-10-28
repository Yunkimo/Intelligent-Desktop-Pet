"""带现有 API Key 鉴权的只读天气/搜索接口。"""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response

from ..auth import require_token
from ..web_query import QueryResult, WebQueryError, validate_input

router = APIRouter(prefix="/api/tools", tags=["web-query"], dependencies=[Depends(require_token)])


def checked(value: str, *, city: bool = False) -> str:
    """把输入错误转为 422，不发起上游请求。"""
    try:
        return validate_input(value, city=city)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None


@router.get("/weather", response_model=QueryResult)
async def weather(
    request: Request, response: Response, city: Annotated[str, Query(min_length=1, max_length=80)]
) -> QueryResult:
    """返回带来源及观测时间的天气摘要。"""
    city = checked(city, city=True)
    response.headers["Cache-Control"] = "no-store"
    try:
        return await request.app.state.web_query_client.weather(city)
    except WebQueryError as exc:
        raise HTTPException(status_code=exc.status, detail=exc.code) from None


@router.get("/search", response_model=QueryResult)
async def search(
    request: Request,
    response: Response,
    q: Annotated[str, Query(min_length=1, max_length=200)],
    limit: Annotated[int, Query(ge=1, le=5)] = 3,
) -> QueryResult:
    """返回至多五条搜索摘要；无结果和上游失败分别报告。"""
    query = checked(q)
    response.headers["Cache-Control"] = "no-store"
    try:
        return await request.app.state.web_query_client.search(query, limit)
    except WebQueryError as exc:
        raise HTTPException(status_code=exc.status, detail=exc.code) from None
