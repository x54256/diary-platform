from datetime import date, datetime, time
from typing import Literal, Optional
from uuid import UUID
from pydantic import BaseModel, ConfigDict, field_validator, model_validator

RecurrenceType = Literal["NONE", "DAILY", "WEEKLY", "MONTHLY_DATE", "MONTHLY_NTH_WEEKDAY", "YEARLY", "WORKDAY", "REST_DAY"]

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
    recurrence_month: Optional[int] = None
    nth_week: Optional[int] = None
    nth_weekday: Optional[int] = None
    recurrence_month: Optional[int] = None
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
        if self.recurrence_until and self.recurrence_until < self.start_date:
            raise ValueError("截止日期不能早于开始日期")
        if self.recurrence_until and self.recurrence_count: raise ValueError("循环截止日期和次数只能选择一个")
        if self.interval < 1: raise ValueError("循环间隔必须大于等于 1")
        if self.recurrence_count is not None and self.recurrence_count < 1: raise ValueError("重复次数必须大于等于 1")
        if self.recurrence_type == "NONE" and (self.recurrence_until or self.recurrence_count):
            raise ValueError("不循环日程不能设置截止日期或重复次数")
        if self.recurrence_type == "WEEKLY" and any(value not in range(7) for value in self.weekdays):
            raise ValueError("每周重复日期无效")
        if self.recurrence_type == "WEEKLY" and not self.weekdays: raise ValueError("每周重复必须选择日期")
        if self.recurrence_type == "MONTHLY_DATE" and self.month_day is None: raise ValueError("每月重复必须填写日期")
        if self.recurrence_type == "MONTHLY_NTH_WEEKDAY" and (self.nth_week not in {1, 2, 3, 4, 5} or self.nth_weekday not in range(7)):
            raise ValueError("每月第 N 个星期几规则不完整")
        if self.recurrence_type == "YEARLY" and (self.recurrence_month not in range(1, 13) or self.month_day not in range(1, 32)):
            raise ValueError("每年重复必须填写月份和日期")
        return self

class ScheduleOccurrenceResponse(BaseModel):
    id: UUID; task_id: UUID; scheduled_date: date; title: str; is_all_day: bool
    start_time: Optional[time] = None; end_time: Optional[time] = None
    status: str; completed_at: Optional[datetime] = None; execution_note: Optional[str] = None
    recurrence_type: RecurrenceType = "NONE"
    recurrence_until: Optional[date] = None
    recurrence_count: Optional[int] = None
    interval: int = 1
    weekdays: list[int] = []
    nth_week: Optional[int] = None
    nth_weekday: Optional[int] = None
    model_config = ConfigDict(from_attributes=True)

class ScheduleOccurrenceComplete(BaseModel):
    completed: bool

class ScheduleOccurrenceNoteUpdate(BaseModel):
    execution_note: Optional[str] = None

    @field_validator("execution_note")
    @classmethod
    def normalize_note(cls, value):
        if value is None:
            return None
        value = value.strip()
        return value or None

class ScheduleOccurrenceUpdate(BaseModel):
    title: str
    is_all_day: bool = False
    start_time: Optional[time] = None
    end_time: Optional[time] = None
    recurrence_type: RecurrenceType = "NONE"
    interval: int = 1
    weekdays: list[int] = []
    month_day: Optional[int] = None
    recurrence_month: Optional[int] = None
    nth_week: Optional[int] = None
    nth_weekday: Optional[int] = None
    recurrence_until: Optional[date] = None
    recurrence_count: Optional[int] = None
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
        if self.recurrence_type == "NONE" and self.recurrence_until:
            raise ValueError("不循环日程不能设置截止日期")
        if self.recurrence_type == "NONE" and self.recurrence_count:
            raise ValueError("不循环日程不能设置重复次数")
        if self.recurrence_until and self.recurrence_count:
            raise ValueError("循环截止日期和次数只能选择一个")
        if self.interval < 1: raise ValueError("循环间隔必须大于等于 1")
        if self.recurrence_count is not None and self.recurrence_count < 1: raise ValueError("重复次数必须大于等于 1")
        if self.recurrence_type == "WEEKLY" and any(value not in range(7) for value in self.weekdays):
            raise ValueError("每周重复日期无效")
        if self.recurrence_type == "WEEKLY" and not self.weekdays: raise ValueError("每周重复必须选择日期")
        if self.recurrence_type == "MONTHLY_DATE" and self.month_day is None: raise ValueError("每月重复必须填写日期")
        if self.recurrence_type == "MONTHLY_NTH_WEEKDAY" and (self.nth_week not in {1, 2, 3, 4, 5} or self.nth_weekday not in range(7)):
            raise ValueError("每月第 N 个星期几规则不完整")
        if self.recurrence_type == "YEARLY" and (self.recurrence_month not in range(1, 13) or self.month_day not in range(1, 32)):
            raise ValueError("每年重复必须填写月份和日期")
        return self
