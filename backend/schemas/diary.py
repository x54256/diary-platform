"""日记相关的请求/响应模型"""

from datetime import date, datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel

from schemas.tag import TagResponse


class DiaryCreate(BaseModel):
    """创建日记请求"""

    original_text: str
    diary_date: date
    tag_ids: list[UUID] = []


class DiaryUpdate(BaseModel):
    """更新日记请求"""

    original_text: Optional[str] = None
    diary_date: Optional[date] = None
    status: Optional[str] = None


class DiaryOrganizedResponse(BaseModel):
    """日记整理内容响应"""

    id: UUID
    title: Optional[str] = None
    summary: Optional[str] = None
    content: Optional[str] = None
    mood: Optional[str] = None
    location: Optional[str] = None

    class Config:
        from_attributes = True


class DiaryResponse(BaseModel):
    """日记信息响应"""

    id: UUID
    user_id: UUID
    original_text: str
    diary_date: date
    status: str
    created_at: datetime
    updated_at: datetime
    organized: Optional[DiaryOrganizedResponse] = None
    tags: list[TagResponse] = []

    class Config:
        from_attributes = True


class DiaryOrganizedUpdate(BaseModel):
    """修改整理内容的请求体"""

    title: Optional[str] = None
    summary: Optional[str] = None
    content: Optional[str] = None
    mood: Optional[str] = None
    location: Optional[str] = None


class DiaryCalendarItem(BaseModel):
    """日历视图数据项"""

    diary_date: date
    mood: Optional[str] = None
    status: str


class DiaryTagsUpdate(BaseModel):
    """更新日记标签的请求体"""

    tag_ids: list[UUID] = []


class OrganizeTaskResponse(BaseModel):
    """异步整理任务状态响应"""

    diary_id: UUID
    status: str  # running / completed / failed
    current_step: Optional[str] = None  # text_cleaning / deep_cleaning / event_organizing / template_filling / content_checking / metadata_generating
    error_message: Optional[str] = None
