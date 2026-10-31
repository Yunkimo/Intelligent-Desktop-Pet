"""学期配置与日期查询；沿用共享演示鉴权，B8 再接入认证用户。"""

from datetime import date
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, ConfigDict, Field, field_validator
from starlette.concurrency import run_in_threadpool

from .. import semester
from ..auth import require_token

router = APIRouter(prefix="/api", tags=["semester"], dependencies=[Depends(require_token)])


class SemesterIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    start_date: date
    total_weeks: int = Field(ge=1, le=53, strict=True)
    timezone: str = "Asia/Shanghai"

    @field_validator("start_date", mode="before")
    @classmethod
    def validate_date(cls, value):
        """只接受明确的 ISO 日期，拒绝时间戳及日期时间。"""
        if not isinstance(value, str) or len(value) != 10:
            raise ValueError("start_date 必须是 YYYY-MM-DD")
        day = date.fromisoformat(value)
        if day.isoweekday() != 1:
            raise ValueError("第一周起始日期必须是周一")
        return day

    @field_validator("timezone")
    @classmethod
    def validate_timezone(cls, value):
        """确认 IANA 时区数据可用，拒绝未知名称。"""
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError):
            raise ValueError("timezone 必须是有效 IANA 时区") from None
        return value


@router.get("/semester")
def get_semester():
    return semester.get_settings()


@router.put("/semester")
async def put_semester(payload: SemesterIn, request: Request):
    result = await run_in_threadpool(
        semester.save_settings,
        payload.start_date.isoformat(),
        payload.total_weeks,
        payload.timezone,
    )
    await request.app.state.push_service.notify("semester.updated", 1)
    return result


@router.get("/calendar")
def get_calendar(date: date | None = None):
    return semester.calendar(date)
