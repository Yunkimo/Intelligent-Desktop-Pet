"""提醒 CRUD 路由。"""

import sqlite3

from fastapi import APIRouter, Depends, HTTPException

from .. import db, reminder_store, wechat_store
from ..auth import require_token
from ..schemas import ReminderIn, ReminderUpdate

router = APIRouter(
    prefix="/api/reminders", tags=["reminders"], dependencies=[Depends(require_token)]
)


@router.get("")
def list_reminders():
    return db.list_reminders()


@router.get("/{reminder_id}/delivery")
def delivery_status(reminder_id: int) -> dict:
    """查询提醒的 WebSocket 发送尝试状态。"""
    delivery = reminder_store.delivery_status(reminder_id)
    if delivery is None:
        raise HTTPException(status_code=404, detail="提醒不存在")
    delivery["wechat"] = wechat_store.status(reminder_id)
    return delivery


@router.post("", status_code=201)
def create_reminder(payload: ReminderIn):
    try:
        return db.create_reminder(**payload.model_dump())
    except sqlite3.IntegrityError:
        raise HTTPException(status_code=422, detail="微信接收用户不存在") from None


@router.put("/{reminder_id}")
def update_reminder(reminder_id: int, payload: ReminderUpdate):
    try:
        reminder = db.update_reminder(reminder_id, payload.model_dump(exclude_unset=True))
    except sqlite3.IntegrityError:
        raise HTTPException(status_code=422, detail="微信接收用户不存在") from None
    if reminder is None:
        raise HTTPException(status_code=404, detail="提醒不存在")
    return reminder


@router.delete("/{reminder_id}", status_code=204)
def delete_reminder(reminder_id: int):
    if not db.delete_reminder(reminder_id):
        raise HTTPException(status_code=404, detail="提醒不存在")
