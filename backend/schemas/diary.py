"""日记相关的请求/响应模型"""

from datetime import date, datetime
from typing import Optional
from uuid import UUID

import json

from pydantic import BaseModel, field_validator

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
    introduction: Optional[str] = None
    trivia: Optional[list[str]] = None
    plans: Optional[list[str]] = None
    events: list["DiaryEventResponse"] = []
    check_logs: list["CheckLogResponse"] = []
    clean_check_logs: list["CleanCheckLogResponse"] = []

    @field_validator("trivia", "plans", mode="before")
    @classmethod
    def parse_json_string(cls, v):
        if isinstance(v, str):
            return json.loads(v)
        return v

    class Config:
        from_attributes = True


class DiaryEventResponse(BaseModel):
    """日记事件响应"""

    id: UUID
    event_title: Optional[str] = None
    body: Optional[list[str]] = None
    feeling: Optional[list[str]] = None
    reflection: Optional[list[str]] = None
    event_tags: Optional[dict] = None
    sort_order: int = 0

    @field_validator("body", "feeling", "reflection", "event_tags", mode="before")
    @classmethod
    def parse_json_string(cls, v):
        if isinstance(v, str):
            try:
                parsed = json.loads(v)
                # 兼容旧数据：如果解析结果仍是字符串（非列表），包装为列表
                if isinstance(parsed, str):
                    return [parsed] if parsed else []
                return parsed
            except (json.JSONDecodeError, ValueError):
                # 旧数据可能是纯字符串，包装为单元素列表
                return [v] if v else []
        return v

    class Config:
        from_attributes = True


class CheckLogResponse(BaseModel):
    """内容审核日志响应"""

    id: UUID
    check_item: Optional[str] = None
    status: Optional[str] = None
    target: Optional[str] = None
    issue: Optional[str] = None
    before: Optional[str] = None
    after: Optional[str] = None
    reason: Optional[str] = None
    sort_order: int = 0

    class Config:
        from_attributes = True


class CleanCheckLogResponse(BaseModel):
    """清洗审核日志响应"""

    id: UUID
    issue: Optional[str] = None
    before: Optional[str] = None
    after: Optional[str] = None
    reason: Optional[str] = None
    sort_order: int = 0

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
    current_step: Optional[str] = None  # text_cleaning / clean_checking / event_organizing / structuring / content_checking / metadata_extracting
    error_message: Optional[str] = None


# 解决前向引用
DiaryOrganizedResponse.model_rebuild()
