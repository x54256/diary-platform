"""日记相关的请求/响应模型"""

from datetime import date, datetime
from typing import Optional
from uuid import UUID

import json

from pydantic import BaseModel, ConfigDict, field_validator

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
    is_dirty: Optional[bool] = None


class DiaryAnalysisResponse(BaseModel):
    """日记分析结果响应"""

    id: UUID
    mood: Optional[str] = None
    emotion_analyses: Optional[list] = None
    behavior_decision_analyses: Optional[list] = None
    self_understanding_analyses: Optional[list] = None
    action_suggestions: Optional[list] = None
    cognitive_calibration_analyses: Optional[list] = None
    cognitive_enhancements: Optional[list] = None
    analyzed_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)

    @field_validator(
        "emotion_analyses",
        "behavior_decision_analyses",
        "self_understanding_analyses",
        "action_suggestions",
        "cognitive_calibration_analyses",
        "cognitive_enhancements",
        mode="before",
    )
    @classmethod
    def parse_json_list(cls, v):
        if isinstance(v, str):
            try:
                return json.loads(v)
            except (json.JSONDecodeError, TypeError):
                return []
        return v if v is not None else []


class DiaryOrganizedResponse(BaseModel):
    """日记整理内容响应"""

    id: UUID
    title: Optional[str] = None           # 日记标题
    summary: Optional[str] = None          # 摘要（1个自然段，2-4句）
    content: Optional[str] = None
    mood: Optional[str] = None
    location: Optional[str] = None
    introduction: Optional[str] = None
    trivia: Optional[list[str]] = None
    plans: Optional[list[str]] = None
    events: list["DiaryEventResponse"] = []
    check_logs: list["CheckLogResponse"] = []
    clean_check_logs: list["CleanCheckLogResponse"] = []
    analysis: Optional[DiaryAnalysisResponse] = None

    @field_validator("trivia", "plans", mode="before")
    @classmethod
    def parse_json_string(cls, v):
        if isinstance(v, str):
            return json.loads(v)
        return v

    model_config = ConfigDict(from_attributes=True)


class DiaryEventResponse(BaseModel):
    """日记事件响应"""

    id: UUID
    event_title: Optional[str] = None
    body: Optional[list[str]] = None
    feeling: Optional[list[str]] = None
    reflection: Optional[list[str]] = None
    event_tags: Optional[dict] = None
    analysis: Optional[dict] = None
    sort_order: int = 0
    tags: list[TagResponse] = []

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

    @field_validator("analysis", mode="before")
    @classmethod
    def parse_analysis(cls, v):
        if isinstance(v, str):
            try:
                return json.loads(v)
            except (json.JSONDecodeError, TypeError):
                return None
        return v

    model_config = ConfigDict(from_attributes=True)


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

    model_config = ConfigDict(from_attributes=True)


class CleanCheckLogResponse(BaseModel):
    """清洗审核日志响应"""

    id: UUID
    issue: Optional[str] = None
    before: Optional[str] = None
    after: Optional[str] = None
    reason: Optional[str] = None
    sort_order: int = 0

    model_config = ConfigDict(from_attributes=True)


class DiaryResponse(BaseModel):
    """日记信息响应"""

    id: UUID
    user_id: UUID
    original_text: str
    diary_date: date
    status: str
    is_dirty: bool = False
    created_at: datetime
    updated_at: datetime
    organized: Optional[DiaryOrganizedResponse] = None
    tags: list[TagResponse] = []

    model_config = ConfigDict(from_attributes=True)


class DiaryEventUpdate(BaseModel):
    """单个事件的更新数据"""

    id: UUID
    event_title: Optional[str] = None
    body: Optional[list[str]] = None
    feeling: Optional[list[str]] = None
    reflection: Optional[list[str]] = None


class DiaryOrganizedUpdate(BaseModel):
    """修改整理内容的请求体"""

    title: Optional[str] = None
    summary: Optional[str] = None
    content: Optional[str] = None
    mood: Optional[str] = None
    location: Optional[str] = None
    introduction: Optional[str] = None
    trivia: Optional[list[str]] = None
    plans: Optional[list[str]] = None
    events: Optional[list[DiaryEventUpdate]] = None


class DiaryCalendarItem(BaseModel):
    """日历视图数据项"""

    diary_date: date
    mood: Optional[str] = None
    status: str
    is_dirty: bool = False


class DiaryTagsUpdate(BaseModel):
    """更新日记标签的请求体"""

    tag_ids: list[UUID] = []


class OrganizeTaskResponse(BaseModel):
    """异步整理/分析任务状态响应"""

    diary_id: UUID
    status: str  # running / completed / failed
    task_type: Optional[str] = None  # organize（整理）/ analyze（分析）
    current_step: Optional[str] = None  # text_cleaning / clean_checking / event_organizing / structuring / content_checking / metadata_extracting
    error_message: Optional[str] = None


# 解决前向引用
DiaryOrganizedResponse.model_rebuild()
