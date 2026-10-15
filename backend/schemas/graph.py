"""图谱公开接口，只暴露进度及正式结果。"""

from datetime import date
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, model_validator


class HistoryBuildRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    date_from: date
    date_to: date

    @model_validator(mode="after")
    def ordered(self):
        if self.date_from > self.date_to: raise ValueError("起始日期不能晚于结束日期")
        return self


class GraphTaskResponse(BaseModel):
    task_id: UUID
    entry_type: Literal["ANALYSIS", "HISTORY"]
    status: Literal["QUEUED", "RUNNING", "SUCCEEDED", "FAILED", "SUPERSEDED"]
    date_from: date
    date_to: date
    current_run_id: UUID | None = None
    current_diary_id: UUID | None = None
    current_date: date | None = None
    current_step: str | None = None
    total_days: int
    published_days: int
    skipped_days: int
    failed_days: int
    pending_days: int
    error: dict[str, Any] | None = None
    can_retry: bool
    runs: list[dict[str, Any]]


class GraphResultResponse(BaseModel):
    diary_id: UUID
    run: dict[str, Any] | None
    events: list[dict[str, Any]]
    relations: list[dict[str, Any]]
