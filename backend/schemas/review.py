"""定期回顾 API 的请求与响应契约。"""

from datetime import date, datetime
from typing import Any, Literal, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


ReviewTypeValue = Literal["WEEK", "MONTH", "QUARTER", "YEAR"]
ReviewVersionTypeValue = Literal["GENERATED", "REGENERATED", "EVENT_EDITED", "ANALYSIS_UPDATED"]
ReviewTriggerTypeValue = Literal["AUTO", "MANUAL", "REGENERATE", "RETRY"]
ReviewGenerationModeValue = Literal["FULL", "ANALYSIS_ONLY"]
ReviewTaskStatusValue = Literal["PENDING_START", "QUEUED", "RUNNING", "SUCCEEDED", "FAILED", "SKIPPED_NO_DATA"]
ReviewTaskStepValue = Literal[
    "FREEZE_SOURCES",
    "LOAD_BASE_EVENT",
    "EVENT_ORGANIZE",
    "ANALYSIS_ACTION",
    "PERSIST_VERSION",
]
# 新五领域码；写入校验走 review_ai 的 ALL_DOMAIN_CODES。
# 响应侧领域字段用 str 放宽：历史版本的旧六码行动可安全透传展示（前端有未知码回退）。
ReviewDomainValue = Literal[
    "WORK_OUTPUT",
    "PERSONAL_GROWTH",
    "HEALTH_WELLBEING",
    "RELATIONSHIPS",
    "LIFE_AFFAIRS",
]
ReviewAngleValue = Literal[
    "EMOTION_REGULATION",
    "BEHAVIOR_EXECUTION",
    "DECISION_PROBLEM_SOLVING",
    "ATTENTION_MOTIVATION_VALUES",
    "COGNITION_LEARNING",
    "CAPABILITY_GROWTH",
    "RELATIONSHIP_SOCIAL_PSYCHOLOGY",
]
ReviewActionStatusValue = Literal["CANDIDATE", "CONFIRMED", "IGNORED"]
ReviewActionCheckStatusValue = Literal[
    "FULFILLED",
    "PARTIALLY_FULFILLED",
    "EXPLICITLY_NOT_FULFILLED",
    "NOT_ASSESSABLE",
]


class ReviewTaskCreate(BaseModel):
    """手动创建已结束周期的首次生成任务。"""

    review_type: ReviewTypeValue
    period_start: date


class ReviewEventThreadEdit(BaseModel):
    thread_id: str = Field(min_length=1, max_length=200)
    narrative: str = Field(min_length=1)

    @field_validator("thread_id", "narrative")
    @classmethod
    def trim_required_text(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("内容不能为空")
        return value


class ReviewEventDocumentUpdate(BaseModel):
    """事件层只允许提交被修改主线的叙事。"""

    threads: list[ReviewEventThreadEdit] = Field(min_length=1)

    @model_validator(mode="after")
    def unique_threads(self):
        thread_ids = [item.thread_id for item in self.threads]
        if len(thread_ids) != len(set(thread_ids)):
            raise ValueError("不能重复修改同一条事件主线")
        return self


class ReviewFeedbackUpsert(BaseModel):
    rating: Optional[int] = Field(default=None, ge=1, le=5)
    comment: Optional[str] = None

    @field_validator("comment")
    @classmethod
    def normalize_comment(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        value = value.strip()
        return value or None

    @model_validator(mode="after")
    def require_feedback(self):
        if self.rating is None and self.comment is None:
            raise ValueError("评分和文字反馈至少填写一项")
        return self


class ReviewActionUpdate(BaseModel):
    status: Optional[ReviewActionStatusValue] = None
    edited_content: Optional[str] = None

    @field_validator("edited_content")
    @classmethod
    def normalize_content(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        value = value.strip()
        if not value:
            raise ValueError("行动内容不能为空")
        return value

    @model_validator(mode="after")
    def require_change(self):
        if self.status is None and self.edited_content is None:
            raise ValueError("至少需要修改一项行动数据")
        return self


class ReviewResponse(BaseModel):
    id: UUID
    user_id: UUID
    review_type: ReviewTypeValue
    period_start: date
    period_end: date
    current_version_id: Optional[UUID] = None
    is_unread: bool
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class ReviewListItemResponse(BaseModel):
    id: UUID
    review_type: ReviewTypeValue
    period_start: date
    period_end: date
    current_version_id: Optional[UUID] = None
    current_version_no: Optional[int] = None
    version_count: int = 0
    summary: str = ""
    is_unread: bool = False
    analysis_stale: bool = False
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class ReviewListResponse(BaseModel):
    items: list[ReviewListItemResponse] = Field(default_factory=list)
    next_cursor: Optional[str] = None


class ReviewVersionResponse(BaseModel):
    id: UUID
    review_id: UUID
    user_id: UUID
    version_no: int
    version_type: ReviewVersionTypeValue
    base_version_id: Optional[UUID] = None
    source_set_id: UUID
    event_document: dict[str, Any] = Field(default_factory=dict)
    analysis_document: dict[str, Any] = Field(default_factory=dict)
    summary: str = ""
    analysis_stale: bool = False
    superseded_at_creation: bool = False
    missing_periods: list[dict[str, Any]] = Field(default_factory=list)
    event_model_info: Optional[dict[str, Any]] = None
    analysis_model_info: Optional[dict[str, Any]] = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class ReviewVersionSummaryResponse(BaseModel):
    id: UUID
    version_no: int
    version_type: ReviewVersionTypeValue
    summary: str = ""
    analysis_stale: bool = False
    superseded_at_creation: bool = False
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class ReviewFeedbackResponse(BaseModel):
    id: UUID
    version_id: UUID
    analysis_item_id: UUID
    angle_code: ReviewAngleValue
    rating: Optional[int] = None
    comment: Optional[str] = None
    is_inherited: bool = False
    source_feedback_id: Optional[UUID] = None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class ReviewActionResponse(BaseModel):
    id: UUID
    version_id: UUID
    primary_domain: str
    related_domains: list[str] = Field(default_factory=list)
    content: str
    edited_content: Optional[str] = None
    rationale: Optional[str] = None
    status: ReviewActionStatusValue
    source_action_id: Optional[UUID] = None
    is_inherited: bool = False
    basis_analysis_ids: list[UUID] = Field(default_factory=list)
    basis_source_ids: list[UUID] = Field(default_factory=list)
    verification_rule: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class ReviewActionCheckResponse(BaseModel):
    id: UUID
    version_id: UUID
    previous_action_id: UUID
    primary_domain: str
    previous_action_content: str
    check_status: ReviewActionCheckStatusValue
    explanation: str
    evidence_source_ids: list[UUID] = Field(default_factory=list)
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class ReviewDependencyResponse(BaseModel):
    id: UUID
    dependency_type: Literal["LOWER_PERIOD", "PRIOR_SAME_LEVEL"]
    dependency_review_id: Optional[UUID] = None
    dependency_version_id: Optional[UUID] = None
    period_start: date
    period_end: date
    status: Literal["AVAILABLE", "MISSING", "FAILED", "SKIPPED_NO_DATA"]
    context_only: bool = False

    model_config = ConfigDict(from_attributes=True)


class ReviewDetailResponse(BaseModel):
    review: ReviewResponse
    version: ReviewVersionResponse
    feedback: list[ReviewFeedbackResponse] = Field(default_factory=list)
    actions: list[ReviewActionResponse] = Field(default_factory=list)
    action_checks: list[ReviewActionCheckResponse] = Field(default_factory=list)
    dependencies: list[ReviewDependencyResponse] = Field(default_factory=list)
    source_updates_available: bool = False


class ReviewTaskResponse(BaseModel):
    id: UUID
    review_id: UUID
    user_id: UUID
    review_type: ReviewTypeValue
    period_start: date
    period_end: date
    trigger_type: ReviewTriggerTypeValue
    generation_mode: ReviewGenerationModeValue
    base_version_id: Optional[UUID] = None
    retry_of_task_id: Optional[UUID] = None
    status: ReviewTaskStatusValue
    current_step: ReviewTaskStepValue
    freeze_attempts: int = 0
    event_attempts: int = 0
    analysis_attempts: int = 0
    error_code: Optional[str] = None
    error_message: Optional[str] = None
    requested_start_at: Optional[datetime] = None
    started_by_user_id: Optional[UUID] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    result_version_id: Optional[UUID] = None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class ReviewTaskListResponse(BaseModel):
    items: list[ReviewTaskResponse] = Field(default_factory=list)
    next_cursor: Optional[str] = None


class ReviewDailyDigestResponse(BaseModel):
    id: UUID
    review_task_id: UUID
    review_version_id: Optional[UUID] = None
    digest_date: date
    status: Literal["EMPTY", "READY", "FAILED"]
    material_document: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class ReviewDailyDigestListResponse(BaseModel):
    items: list[ReviewDailyDigestResponse] = Field(default_factory=list)
    next_cursor: Optional[str] = None


class ReviewSourceResponse(BaseModel):
    id: UUID
    root_fact_id: str
    source_type: Literal[
        "DIARY_EVENT",
        "SCHEDULE_OCCURRENCE",
        "LOWER_REVIEW_EVENT",
        "LOWER_REVIEW_ANALYSIS",
        "PRIOR_REVIEW_EVENT",
        "USER_FACT_CORRECTION",
    ]
    root_source_type: str
    fact_kind: Literal[
        "USER_FACT",
        "USER_SELF_REPORT",
        "SCHEDULE_RECORD",
        "AI_ANALYSIS",
        "USER_CORRECTION",
        "REVIEW_DERIVED",
    ]
    source_date: date
    period_role: Literal["CURRENT", "CONTEXT_ONLY", "OUT_OF_PERIOD"]
    relative_position: Optional[Literal["BEFORE", "AFTER"]] = None
    origin_review_id: Optional[UUID] = None
    origin_review_version_id: Optional[UUID] = None
    origin_content_item_type: Optional[str] = None
    origin_content_item_id: Optional[UUID] = None
    origin_content_item_key: Optional[str] = None
    lineage: list[dict[str, Any]] = Field(default_factory=list)
    content: str
    snapshot: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)
