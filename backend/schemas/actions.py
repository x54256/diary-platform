"""日记行动项请求与响应模型。"""

from datetime import date, datetime, time
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

RecurrenceType = Literal[
    "NONE", "DAILY", "WEEKLY", "MONTHLY_DATE", "MONTHLY_NTH_WEEKDAY",
    "YEARLY", "WORKDAY", "REST_DAY",
]


class ActionSchedulePayload(BaseModel):
    title: str | None = None
    is_all_day: bool = True
    start_date: date
    start_time: time | None = None
    end_time: time | None = None
    recurrence_type: RecurrenceType = "NONE"
    interval: int = Field(default=1, ge=1)
    weekdays: list[int] = Field(default_factory=list)
    month_day: int | None = None
    nth_week: int | None = None
    nth_weekday: int | None = None
    recurrence_until: date | None = None
    recurrence_count: int | None = Field(default=None, ge=1)

    @model_validator(mode="after")
    def validate_schedule(self):
        if not self.is_all_day and (not self.start_time or not self.end_time or self.end_time <= self.start_time):
            raise ValueError("定时日程必须填写有效的开始和结束时间")
        if self.is_all_day:
            self.start_time = None
            self.end_time = None
        if self.recurrence_until and self.recurrence_until < self.start_date:
            raise ValueError("截止日期不能早于开始日期")
        if self.recurrence_until and self.recurrence_count:
            raise ValueError("循环截止日期和次数只能选择一个")
        if self.recurrence_type == "NONE" and (self.recurrence_until or self.recurrence_count):
            raise ValueError("不循环日程不能设置截止日期或次数")
        if self.recurrence_type == "WEEKLY" and any(value not in range(7) for value in self.weekdays):
            raise ValueError("每周重复日期无效")
        if self.recurrence_type == "MONTHLY_NTH_WEEKDAY" and (
            self.nth_week not in {1, 2, 3, 4, 5} or self.nth_weekday not in range(7)
        ):
            raise ValueError("每月第 N 个星期几规则不完整")
        return self


class DiaryActionUpdate(BaseModel):
    title: str | None = None
    schedule: ActionSchedulePayload | None = None

    @field_validator("title")
    @classmethod
    def normalize_title(cls, value):
        if value is None:
            return value
        value = value.strip()
        if not value:
            raise ValueError("行动名称不能为空")
        return value


class DiaryActionCompletion(BaseModel):
    completed: bool


class DiaryActionSyncItem(BaseModel):
    action_id: UUID
    schedule: ActionSchedulePayload


class DiaryActionSyncRequest(BaseModel):
    items: list[DiaryActionSyncItem] = Field(min_length=1)


class DiaryActionScheduleResponse(BaseModel):
    task_id: UUID | None = None
    occurrence_id: UUID | None = None
    status: Literal["unsynced", "synced", "schedule_deleted"]


class DiaryActionResponse(BaseModel):
    id: UUID
    diary_id: UUID
    generation_run_id: UUID
    source_kind: str
    source_refs: dict
    title: str
    is_all_day: bool
    start_date: date
    start_time: time | None = None
    end_time: time | None = None
    recurrence_type: RecurrenceType
    interval: int
    weekdays: list[int]
    month_day: int | None = None
    nth_week: int | None = None
    nth_weekday: int | None = None
    recurrence_until: date | None = None
    recurrence_count: int | None = None
    status: Literal["pending", "completed"]
    completed_at: datetime | None = None
    user_modified: bool
    sort_order: int
    schedule: DiaryActionScheduleResponse
    model_config = ConfigDict(from_attributes=True)
