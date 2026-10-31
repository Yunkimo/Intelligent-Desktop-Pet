"""课表 CRUD 路由。"""

from fastapi import APIRouter, Depends, HTTPException, Request
from starlette.concurrency import run_in_threadpool

from .. import db
from ..auth import require_token
from ..schemas import CourseIn, CourseUpdate

router = APIRouter(prefix="/api/courses", tags=["courses"], dependencies=[Depends(require_token)])


@router.get("")
def list_courses():
    return db.list_courses()


@router.post("", status_code=201)
async def create_course(payload: CourseIn, request: Request) -> dict:
    """在线程池提交课表后发送通知，保持原 REST 响应。"""
    course = await run_in_threadpool(db.create_course, **payload.model_dump())
    await request.app.state.push_service.notify("course.created", course["id"])
    return course


@router.put("/{course_id}")
async def update_course(course_id: int, payload: CourseUpdate, request: Request):
    course = await run_in_threadpool(
        db.update_course, course_id, payload.model_dump(exclude_unset=True)
    )
    if course is None:
        raise HTTPException(status_code=404, detail="课表条目不存在")
    await request.app.state.push_service.notify("course.updated", course_id)
    return course


@router.delete("/{course_id}", status_code=204)
async def delete_course(course_id: int, request: Request):
    if not await run_in_threadpool(db.delete_course, course_id):
        raise HTTPException(status_code=404, detail="课表条目不存在")
    await request.app.state.push_service.notify("course.deleted", course_id)
