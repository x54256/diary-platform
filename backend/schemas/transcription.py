"""语音转写接口模型。"""

from __future__ import annotations

from datetime import date, datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class TranscriptionStart(BaseModel):
    diary_date: date
    base_text: str = ""


class TranscriptionBatchCreate(BaseModel):
    diary_date: date


class TranscriptionItemOrderUpdate(BaseModel):
    item_ids: list[UUID] = Field(min_length=1)


class TranscriptionItemResponse(BaseModel):
    id: UUID
    sort_order: int
    filename: str
    file_size: int
    status: str
    transcript_preview: Optional[str] = None
    error_code: Optional[str] = None
    error_message: Optional[str] = None
    retry_count: int = 0


class TranscriptionBatchResponse(BaseModel):
    id: UUID
    diary_date: Optional[date] = None
    status: str
    diary_id: Optional[UUID] = None
    error_message: Optional[str] = None
    expires_at: Optional[datetime] = None
    items: list[TranscriptionItemResponse] = Field(default_factory=list)

    model_config = ConfigDict(from_attributes=True)


class TranscriptionCancelResponse(BaseModel):
    diary_date: Optional[date] = None
    base_text: str = ""
    status: str
