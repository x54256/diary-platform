"""日记相关的请求/响应模型"""

from datetime import date, datetime
import json
from typing import Literal, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, field_serializer, field_validator

from schemas.common import serialize_utc_datetime
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


class AnalysisFeedbackResponse(BaseModel):
    """分析反馈响应"""

    id: UUID
    rating: int
    comment: Optional[str] = None
    is_inherited: bool = False
    source_feedback_id: Optional[UUID] = None
    updated_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)


class AnalysisItemResponse(BaseModel):
    """单条分析内容响应"""

    id: UUID
    content: str
    question: Optional[str] = None
    sort_order: int = 0

    model_config = ConfigDict(from_attributes=True)


class AnalysisSectionResponse(BaseModel):
    """分析类型块响应"""

    scope: str
    event_id: Optional[UUID] = None
    analysis_type: str
    title: str
    items: list[AnalysisItemResponse] = []
    feedback: Optional[AnalysisFeedbackResponse] = None


class AnalysisRunResponse(BaseModel):
    """当前分析轮次响应"""

    id: UUID
    mood: Optional[str] = None
    status: str
    sections: list[AnalysisSectionResponse] = []
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class AnalysisFeedbackUpsert(BaseModel):
    """保存分析反馈请求"""

    analysis_run_id: UUID
    scope: str
    event_id: Optional[UUID] = None
    analysis_type: str
    rating: int
    comment: Optional[str] = None


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
    analysis: Optional[AnalysisRunResponse] = None

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
    analysis: Optional[list[AnalysisSectionResponse]] = None
    sort_order: int = 0
    tags: list[TagResponse] = []
    is_favorite: bool = False
    ai_importance: Optional[Literal["HIGH", "MEDIUM", "LOW"]] = None
    ai_importance_reason: Optional[str] = None
    user_importance: Optional[Literal["HIGH", "MEDIUM", "LOW"]] = None
    user_importance_reason: Optional[str] = None
    importance_origin: Optional[str] = None

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
    transcription_status: Optional[str] = None
    is_dirty: bool = False
    deleted_at: Optional[datetime] = None
    deleted_by: Optional[UUID] = None
    created_at: datetime
    updated_at: datetime
    organized: Optional[DiaryOrganizedResponse] = None
    tags: list[TagResponse] = []
    is_favorite: bool = False

    model_config = ConfigDict(from_attributes=True)

    @field_serializer("created_at", "updated_at")
    def serialize_datetime(self, value: datetime):
        return serialize_utc_datetime(value)


class FavoriteResponse(BaseModel):
    """收藏列表项。事件收藏始终附带所属日记，便于跳转定位。"""

    id: UUID
    favorite_type: Literal["diary", "event"]
    created_at: datetime
    diary: DiaryResponse
    event: Optional[DiaryEventResponse] = None

    model_config = ConfigDict(from_attributes=True)

    @field_serializer("created_at")
    def serialize_created_at(self, value: datetime):
        return serialize_utc_datetime(value)


class DiaryEventUpdate(BaseModel):
    """单个事件的更新数据"""

    id: UUID
    event_title: Optional[str] = None
    body: Optional[list[str]] = None
    feeling: Optional[list[str]] = None
    reflection: Optional[list[str]] = None
    user_importance: Optional[Literal["HIGH", "MEDIUM", "LOW"]] = None
    user_importance_reason: Optional[str] = None


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


AnnotationTargetType = Literal[
    "EVENT_BODY",
    "EVENT_FEELING",
    "EVENT_REFLECTION",
    "ANALYSIS_ITEM",
]


class DiaryAnnotationCommentResponse(BaseModel):
    id: UUID
    content: str
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class DiaryAnnotationResponse(BaseModel):
    id: UUID
    diary_id: UUID
    target_type: str
    event_id: Optional[UUID] = None
    field_name: Optional[str] = None
    analysis_item_id: Optional[UUID] = None
    start_paragraph: int
    start_offset: int
    end_paragraph: int
    end_offset: int
    selected_text: str
    context_before: Optional[str] = None
    context_after: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    comments: list[DiaryAnnotationCommentResponse] = []

    model_config = ConfigDict(from_attributes=True)


class DiaryAnnotationCreate(BaseModel):
    target_type: AnnotationTargetType
    event_id: Optional[UUID] = None
    field_name: Optional[Literal["body", "feeling", "reflection"]] = None
    analysis_item_id: Optional[UUID] = None
    start_paragraph: int = 0
    start_offset: int = 0
    end_paragraph: int = 0
    end_offset: int = 0
    selected_text: str
    context_before: Optional[str] = None
    context_after: Optional[str] = None
    comment: Optional[str] = None


class DiaryAnnotationCommentUpsert(BaseModel):
    content: str


class OrganizeTaskResponse(BaseModel):
    """异步整理/分析任务状态响应"""

    task_id: Optional[UUID] = None
    graph_run_id: Optional[UUID] = None
    can_retry: bool = False
    diary_id: UUID
    status: str  # running / completed / failed
    task_type: Optional[str] = None  # organize（整理）/ analyze（分析）
    analysis_mode: Optional[str] = None  # ordinary（普通分析）/ feedback（反馈重分析）
    current_step: Optional[str] = None  # text_cleaning / clean_checking / event_organizing / structuring / content_checking
    error_message: Optional[str] = None


# 解决前向引用
DiaryOrganizedResponse.model_rebuild()
