"""课表识别导入路由：图片解析（不落库）与批量落库。"""

import asyncio
import logging
import time

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
from fastapi.routing import APIRoute
from pydantic import BaseModel, Field, ValidationError
from starlette.concurrency import run_in_threadpool

from .. import config, db, vision
from ..auth import require_token
from ..image_header import inspect_image
from ..schemas import CourseIn


class ParseBudgetRoute(APIRoute):
    def get_route_handler(self):
        handler = super().get_route_handler()
        if not self.path.endswith("/parse-image"):
            return handler

        async def limited(request):
            request.state.upload_started = time.monotonic()
            try:
                return await asyncio.wait_for(handler(request), config.PARSE_TIMEOUT_SECONDS)
            except asyncio.TimeoutError:
                raise HTTPException(
                    504, detail={"code": "parse_timeout", "message": "识别超时，请重试"}
                ) from None

        return limited


router = APIRouter(
    prefix="/api/courses",
    tags=["courses"],
    route_class=ParseBudgetRoute,
    dependencies=[Depends(require_token)],
)


class CourseBulkIn(BaseModel):
    courses: list[dict] = Field(min_length=1, max_length=100)


@router.post("/parse-image")
async def parse_course_image(request: Request, image: UploadFile = File(...)) -> dict:
    """解析课表图片为课程列表；只识别，不落库。"""
    data = await image.read(vision.MAX_IMAGE_BYTES + 1)
    logging.getLogger(__name__).info(
        "vision upload_read_ms=%.0f", (time.monotonic() - request.state.upload_started) * 1000
    )
    if not data:
        raise HTTPException(status_code=422, detail="图片内容为空")
    if len(data) > vision.MAX_IMAGE_BYTES:
        raise HTTPException(status_code=413, detail="图片超过 10MB，请压缩后重试")
    try:
        mime, width, height = inspect_image(data)
        if width * height > 16_000_000:
            raise HTTPException(413, detail="图片超过 1600 万像素")
        result = await vision.parse_schedule_image(data, mime)
    except ValueError:
        raise HTTPException(422, detail="无法读取 JPEG 或 PNG 图片头") from None
    except vision.VisionRateLimited:
        raise HTTPException(
            429, detail={"code": "rate_limited", "message": "模型服务繁忙，请稍后重试"}
        ) from None
    except vision.VisionNotConfigured:
        raise HTTPException(
            status_code=503,
            detail=(
                "后端未配置视觉模型（LLM_API_KEY / LLM_BASE_URL / LLM_VISION_MODEL），"
                "请在 backend/.env 设置"
            ),
        ) from None
    except vision.VisionTimeout:
        raise HTTPException(
            status_code=504, detail={"code": "parse_timeout", "message": "视觉模型响应超时，请重试"}
        ) from None
    except vision.VisionError as exc:
        raise HTTPException(status_code=502, detail=f"视觉模型调用失败：{exc}") from None
    if not result["courses"] and not result.get("pending_courses"):
        raise HTTPException(status_code=422, detail="未能从图片中识别出课程，请上传清晰的课表截图")
    return result


@router.post("/bulk", status_code=201)
async def bulk_create_courses(payload: CourseBulkIn, request: Request) -> dict:
    """批量导入课表：逐条 CourseIn 校验，无效条目跳过并返回原因。"""
    valid: list[dict] = []
    skipped: list[dict] = []
    for index, item in enumerate(payload.courses):
        try:
            valid.append(CourseIn.model_validate(item).model_dump())
        except ValidationError as exc:
            skipped.append(
                {
                    "index": index,
                    "reason": exc.errors()[0].get("msg", "字段无效"),
                    "item": item,
                }
            )
    if not valid:
        raise HTTPException(status_code=422, detail="没有可导入的有效课程（字段缺失或格式错误）")
    created = await run_in_threadpool(db.create_courses_bulk, valid)
    # 一批仅提示一次列表刷新，保持旧客户端认识的事件类型和信封。
    await request.app.state.push_service.notify("course.created", created[0]["id"])
    return {"created": created, "skipped": skipped}
