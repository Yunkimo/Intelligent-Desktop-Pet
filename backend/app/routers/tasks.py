"""日程/待办 CRUD 路由。"""

from fastapi import APIRouter, Depends, HTTPException, Request
from starlette.concurrency import run_in_threadpool

from .. import db
from ..auth import current_user
from ..schemas import TaskIn, TaskUpdate
from ..task_parse import TextInput, parse_tasks

router = APIRouter(prefix="/api/tasks", tags=["tasks"], dependencies=[Depends(current_user)])


@router.post("/parse-text")
async def parse_text(payload: TextInput):
    """只返回待确认草稿，沿用 tasks 的鉴权。"""
    return await parse_tasks(payload)


@router.get("")
def list_tasks(user_id: int = Depends(current_user)):
    return db.list_tasks(user_id)


@router.post("", status_code=201)
async def create_task(
    payload: TaskIn, request: Request, user_id: int = Depends(current_user)
) -> dict:
    """在线程池提交日程后发送通知，保持原 REST 响应。"""
    task = await run_in_threadpool(db.create_task, **payload.model_dump(), user_id=user_id)
    await request.app.state.push_service.notify("task.created", task["id"], user_id=user_id)
    return task


@router.put("/{task_id}")
async def update_task(
    task_id: int, payload: TaskUpdate, request: Request, user_id: int = Depends(current_user)
):
    task = await run_in_threadpool(
        db.update_task, task_id, payload.model_dump(exclude_unset=True), user_id=user_id
    )
    if task is None:
        raise HTTPException(status_code=404, detail="日程不存在")
    await request.app.state.push_service.notify("task.updated", task_id, user_id=user_id)
    return task


@router.delete("/{task_id}", status_code=204)
async def delete_task(task_id: int, request: Request, user_id: int = Depends(current_user)):
    if not await run_in_threadpool(db.delete_task, task_id, user_id=user_id):
        raise HTTPException(status_code=404, detail="日程不存在")
    await request.app.state.push_service.notify("task.deleted", task_id, user_id=user_id)


@router.get("/{task_id}")
def get_task(task_id: int, user_id: int = Depends(current_user)):
    row = db._get_by_id("tasks", task_id, user_id)
    if row is None:
        raise HTTPException(404, "resource_not_found")
    return row
