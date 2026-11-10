"""提醒 CRUD 路由。"""

import sqlite3

from fastapi import APIRouter, Depends, HTTPException, Request
from starlette.concurrency import run_in_threadpool

from .. import db, reminder_store, wechat_store
from ..auth import current_user
from ..schemas import ReminderIn, ReminderUpdate

router = APIRouter(
    prefix="/api/reminders", tags=["reminders"], dependencies=[Depends(current_user)]
)


@router.get("")
def list_reminders(user_id: int = Depends(current_user)):
    return db.list_reminders(user_id)


@router.get("/{reminder_id}/delivery")
def delivery_status(reminder_id: int, user_id: int = Depends(current_user)) -> dict:
    """查询提醒的 WebSocket 发送尝试状态。"""
    if db._get_by_id("reminders", reminder_id, user_id) is None:
        raise HTTPException(404, "提醒不存在")
    delivery = reminder_store.delivery_status(reminder_id)
    if delivery is None:
        raise HTTPException(status_code=404, detail="提醒不存在")
    delivery["wechat"] = wechat_store.status(reminder_id)
    return delivery


@router.post("", status_code=201)
async def create_reminder(
    payload: ReminderIn, request: Request, user_id: int = Depends(current_user)
):
    try:
        reminder = await run_in_threadpool(
            db.create_reminder, **payload.model_dump(), user_id=user_id
        )
    except db.OwnershipError:
        raise HTTPException(404, "resource_not_found") from None
    except ValueError as exc:
        raise HTTPException(
            status_code=422 if str(exc) == "repeating_reminder_must_be_independent" else 409,
            detail=str(exc),
        ) from None
    except sqlite3.IntegrityError:
        raise HTTPException(status_code=422, detail="微信接收用户不存在") from None
    await request.app.state.push_service.notify("reminder.created", reminder["id"], user_id)
    return reminder


@router.put("/{reminder_id}")
async def update_reminder(
    reminder_id: int,
    payload: ReminderUpdate,
    request: Request,
    user_id: int = Depends(current_user),
):
    try:
        reminder = await run_in_threadpool(
            db.update_reminder, reminder_id, payload.model_dump(exclude_unset=True), user_id=user_id
        )
    except db.OwnershipError:
        raise HTTPException(404, "resource_not_found") from None
    except ValueError as exc:
        raise HTTPException(
            status_code=422 if str(exc) == "repeating_reminder_must_be_independent" else 409,
            detail=str(exc),
        ) from None
    except sqlite3.IntegrityError:
        raise HTTPException(status_code=422, detail="微信接收用户不存在") from None
    if reminder is None:
        raise HTTPException(status_code=404, detail="提醒不存在")
    await request.app.state.push_service.notify("reminder.updated", reminder_id, user_id)
    return reminder


@router.delete("/{reminder_id}", status_code=204)
async def delete_reminder(reminder_id: int, request: Request, user_id: int = Depends(current_user)):
    if not await run_in_threadpool(db.delete_reminder, reminder_id, user_id):
        raise HTTPException(status_code=404, detail="提醒不存在")
    await request.app.state.push_service.notify("reminder.deleted", reminder_id, user_id)


@router.get("/{reminder_id}")
def get_reminder(reminder_id: int, user_id: int = Depends(current_user)):
    row = db._get_by_id("reminders", reminder_id, user_id)
    if row is None:
        raise HTTPException(404, "resource_not_found")
    return row
