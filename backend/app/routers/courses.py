"""课表 CRUD 路由。"""

from fastapi import APIRouter, Depends, HTTPException, Request
from starlette.concurrency import run_in_threadpool

from .. import db
from ..auth import current_user
from ..schemas import CourseIn, CourseUpdate

router = APIRouter(prefix="/api/courses", tags=["courses"], dependencies=[Depends(current_user)])


@router.get("")
def list_courses(user_id: int = Depends(current_user)):
    return db.list_courses(user_id)


@router.post("", status_code=201)
async def create_course(
    payload: CourseIn, request: Request, user_id: int = Depends(current_user)
) -> dict:
    """在线程池提交课表后发送通知，保持原 REST 响应。"""
    course = await run_in_threadpool(db.create_course, **payload.model_dump(), user_id=user_id)
    await request.app.state.push_service.notify("course.created", course["id"], user_id=user_id)
    return course


@router.put("/{course_id}")
async def update_course(
    course_id: int, payload: CourseUpdate, request: Request, user_id: int = Depends(current_user)
):
    course = await run_in_threadpool(
        db.update_course, course_id, payload.model_dump(exclude_unset=True), user_id=user_id
    )
    if course is None:
        raise HTTPException(status_code=404, detail="课表条目不存在")
    await request.app.state.push_service.notify("course.updated", course_id, user_id=user_id)
    return course


@router.delete("/{course_id}", status_code=204)
async def delete_course(course_id: int, request: Request, user_id: int = Depends(current_user)):
    if not await run_in_threadpool(db.delete_course, course_id, user_id=user_id):
        raise HTTPException(status_code=404, detail="课表条目不存在")
    await request.app.state.push_service.notify("course.deleted", course_id, user_id=user_id)


@router.get("/{course_id}")
def get_course(course_id: int, user_id: int = Depends(current_user)):
    row = db._get_by_id("courses", course_id, user_id)
    if row is None:
        raise HTTPException(404, "resource_not_found")
    return row
