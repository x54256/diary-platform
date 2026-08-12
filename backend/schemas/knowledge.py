"""知识沉淀 API 响应模型。"""

from datetime import date, datetime, time
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class KnowledgeTaskResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    diary_id: UUID
    status: Literal["QUEUED", "RUNNING", "SUCCEEDED", "FAILED"]
    current_step: str | None = None
    retry_count: int
    error_code: str | None = None
    error_message: str | None = None
    created_at: datetime
    started_at: datetime | None = None
    completed_at: datetime | None = None


class DiaryKnowledgeStatusResponse(BaseModel):
    state: Literal["NOT_DEPOSITED", "PROCESSING", "FAILED", "DEPOSITED"]
    model_configured: bool
    available: bool
    blocked_by_other_task: bool = False
    unavailable_reason: str | None = None
    task: KnowledgeTaskResponse | None = None
    atomic_event_count: int = 0


class KnowledgeEventListItem(BaseModel):
    id: UUID
    diary_id: UUID
    source_diary_event_id: UUID
    source_event_order: int
    source_order: int
    title: str
    content: str
    occurred_on: date
    occurred_time: time | None = None
    source_diary_date: date
    source_diary_title: str | None = None
    source_event_title: str | None = None
    created_at: datetime


class KnowledgeEventListResponse(BaseModel):
    items: list[KnowledgeEventListItem]
    next_cursor: str | None = None


class KnowledgeEventDetail(KnowledgeEventListItem):
    source_fragments: list[str]
    source_diary_summary: str | None = None
