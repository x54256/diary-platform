"""知识沉淀 API 响应模型。"""

from datetime import date, datetime, time
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class KnowledgeTaskResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    diary_id: UUID
    task_type: Literal["DEPOSIT", "UPGRADE"] = "DEPOSIT"
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
    content: list[str]
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
    source_diary_summary: str | None = None
    matter: "KnowledgeMatterRef | None" = None


class KnowledgeMatterRef(BaseModel):
    id: UUID
    name: str


class KnowledgeMatterListItem(BaseModel):
    id: UUID
    name: str
    status: Literal["ONGOING", "ENDED", "PAUSED"]
    overview: str
    event_count: int
    last_event_on: date


class KnowledgeMatterListResponse(BaseModel):
    items: list[KnowledgeMatterListItem]
    next_cursor: str | None = None


class KnowledgeMatterEventItem(BaseModel):
    id: UUID
    title: str
    occurred_on: date
    occurred_time: time | None = None
    first_paragraph: str


class KnowledgeMatterDetail(BaseModel):
    id: UUID
    name: str
    status: Literal["ONGOING", "ENDED", "PAUSED"]
    overview: str
    started_on: date
    last_event_on: date
    event_count: int
    created_at: datetime
    events: list[KnowledgeMatterEventItem]


class KnowledgeMatterUpgradeRequest(BaseModel):
    diary_id: UUID


class KnowledgeUpgradePendingDiary(BaseModel):
    diary_id: UUID
    diary_date: date
    diary_title: str | None = None


class KnowledgeUpgradeStatusResponse(BaseModel):
    pending_diaries: list[KnowledgeUpgradePendingDiary]
    active_task: KnowledgeTaskResponse | None = None
