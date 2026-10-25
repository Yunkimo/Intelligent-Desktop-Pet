"""请求体模型（pydantic）。"""

from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from .reminder_time import normalize_reminder_time


class CourseIn(BaseModel):
    name: str
    day_of_week: int = Field(ge=1, le=7)
    start_time: str
    end_time: str
    location: str = ""
    teacher: str = ""
    weeks: list[int] | None = None


class CourseUpdate(BaseModel):
    name: str | None = None
    day_of_week: int | None = Field(default=None, ge=1, le=7)
    start_time: str | None = None
    end_time: str | None = None
    location: str | None = None
    teacher: str | None = None
    weeks: list[int] | None = None


class TaskIn(BaseModel):
    title: str
    note: str = ""
    due_at: str | None = None
    remind_at: str | None = None

    @field_validator("remind_at")
    @classmethod
    def validate_reminder(cls, value: str | None) -> str | None:
        """拒绝非法提醒时间；兼容保留历史任务接口的时间文本形式。"""
        if value is not None:
            normalize_reminder_time(value)
        return value


class TaskUpdate(BaseModel):
    title: str | None = None
    note: str | None = None
    due_at: str | None = None
    remind_at: str | None = None
    done: bool | None = None

    @field_validator("remind_at")
    @classmethod
    def validate_reminder(cls, value: str | None) -> str | None:
        """改期入事务前校验；null 表示清除提醒。"""
        return TaskIn.validate_reminder(value)


class ReminderIn(BaseModel):
    title: str
    body: str = ""
    remind_at: str
    channel: Literal["both", "pc", "phone"] = "both"
    task_id: int | None = None
    wechat_user_id: int | None = Field(default=None, gt=0)

    @field_validator("remind_at")
    @classmethod
    def validate_time(cls, value: str) -> str:
        """校验并统一提醒时间。"""
        return normalize_reminder_time(value)


class ReminderUpdate(BaseModel):
    title: str | None = None
    body: str | None = None
    remind_at: str | None = None
    channel: Literal["both", "pc", "phone"] | None = None
    done: bool | None = None
    task_id: int | None = None
    wechat_user_id: int | None = Field(default=None, gt=0)

    @model_validator(mode="after")
    def validate_update(self) -> "ReminderUpdate":
        """拒绝不可空字段的显式 null，仅允许缺省表示不修改。"""
        for field in self.model_fields_set - {"task_id", "wechat_user_id"}:
            if getattr(self, field) is None:
                raise ValueError(f"{field} 不能为 null")
        if "remind_at" in self.model_fields_set:
            self.remind_at = normalize_reminder_time(self.remind_at)
        return self
