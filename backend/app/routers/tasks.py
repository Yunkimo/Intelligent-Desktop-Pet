"""日程/待办 CRUD 路由。"""

from fastapi import APIRouter, Depends, HTTPException, Request
from starlette.concurrency import run_in_threadpool

from .. import db
from ..auth import require_token
from ..schemas import TaskIn, TaskUpdate
from ..task_parse import TextInput, parse_tasks

router = APIRouter(prefix="/api/tasks", tags=["tasks"], dependencies=[Depends(require_token)])


@router.post("/parse-text")
async def parse_text(payload: TextInput):
    """只返回待确认草稿，沿用 tasks 的鉴权。"""
    return await parse_tasks(payload)


@router.get("")
def list_tasks():
    return db.list_tasks()


@router.post("", status_code=201)
async def create_task(payload: TaskIn, request: Request) -> dict:
    """在线程池提交日程后发送通知，保持原 REST 响应。"""
    task = await run_in_threadpool(db.create_task, **payload.model_dump())
    await request.app.state.push_service.notify("task.created", task["id"])
    return task


@router.put("/{task_id}")
async def update_task(task_id: int, payload: TaskUpdate, request: Request):
    task = await run_in_threadpool(db.update_task, task_id, payload.model_dump(exclude_unset=True))
    if task is None:
        raise HTTPException(status_code=404, detail="日程不存在")
    await request.app.state.push_service.notify("task.updated", task_id)
    return task


@router.delete("/{task_id}", status_code=204)
async def delete_task(task_id: int, request: Request):
    if not await run_in_threadpool(db.delete_task, task_id):
        raise HTTPException(status_code=404, detail="日程不存在")
    await request.app.state.push_service.notify("task.deleted", task_id)
