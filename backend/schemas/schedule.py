from datetime import date, datetime, time
from typing import Literal, Optional
from uuid import UUID
from pydantic import BaseModel, ConfigDict, field_validator, model_validator

RecurrenceType = Literal["NONE", "DAILY", "WEEKLY", "MONTHLY_DATE", "MONTHLY_NTH_WEEKDAY"]

class ScheduleTaskCreate(BaseModel):
    title: str
    is_all_day: bool = False
    start_date: date
    start_time: Optional[time] = None
    end_time: Optional[time] = None
    recurrence_type: RecurrenceType = "NONE"
    interval: int = 1
    weekdays: list[int] = []
    month_day: Optional[int] = None
    nth_week: Optional[int] = None
    nth_weekday: Optional[int] = None
    recurrence_until: Optional[date] = None
    recurrence_count: Optional[int] = None

    @field_validator("title")
    @classmethod
    def title_required(cls, value):
        if not value.strip(): raise ValueError("任务名称不能为空")
        return value.strip()

    @model_validator(mode="after")
    def validate_schedule(self):
        if self.start_date < date.today(): raise ValueError("开始日期不能早于今天")
        if not self.is_all_day and (not self.start_time or not self.end_time or self.end_time <= self.start_time):
            raise ValueError("定时日程必须填写有效的开始和结束时间")
        if self.recurrence_until and self.recurrence_count: raise ValueError("循环截止日期和次数只能选择一个")
        return self

class ScheduleOccurrenceResponse(BaseModel):
    id: UUID; task_id: UUID; scheduled_date: date; title: str; is_all_day: bool
    start_time: Optional[time] = None; end_time: Optional[time] = None
    status: str; completed_at: Optional[datetime] = None; overdue_reason: Optional[str] = None
    recurrence_type: RecurrenceType = "NONE"
    model_config = ConfigDict(from_attributes=True)

class ScheduleOccurrenceComplete(BaseModel):
    completed: bool
    overdue_reason: Optional[str] = None

class ScheduleOccurrenceUpdate(BaseModel):
    title: str
    is_all_day: bool = False
    start_time: Optional[time] = None
    end_time: Optional[time] = None
    scope: Literal["single", "following"] = "single"

    @field_validator("title")
    @classmethod
    def title_required(cls, value):
        if not value.strip(): raise ValueError("任务名称不能为空")
        return value.strip()

    @model_validator(mode="after")
    def validate_schedule(self):
        if not self.is_all_day and (not self.start_time or not self.end_time or self.end_time <= self.start_time):
            raise ValueError("定时日程必须填写有效的开始和结束时间")
        return self
