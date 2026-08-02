"""定期回顾的领域与持久化模型。

回顾正文作为不可变版本保存，来源、反馈、行动和行动核查单独建模，
避免用户操作覆盖历史版本。
"""

import enum
import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import relationship

from database import Base


class StringEnum(str, enum.Enum):
    """数据库使用字符串保存枚举，便于后续增加状态。"""


class ReviewType(StringEnum):
    WEEK = "WEEK"
    MONTH = "MONTH"
    QUARTER = "QUARTER"
    YEAR = "YEAR"


class ReviewVersionType(StringEnum):
    GENERATED = "GENERATED"
    REGENERATED = "REGENERATED"
    EVENT_EDITED = "EVENT_EDITED"
    ANALYSIS_UPDATED = "ANALYSIS_UPDATED"


class ReviewTaskTriggerType(StringEnum):
    AUTO = "AUTO"
    MANUAL = "MANUAL"
    REGENERATE = "REGENERATE"
    RETRY = "RETRY"


class ReviewGenerationMode(StringEnum):
    FULL = "FULL"
    ANALYSIS_ONLY = "ANALYSIS_ONLY"


class ReviewTaskStatus(StringEnum):
    PENDING_START = "PENDING_START"
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    SKIPPED_NO_DATA = "SKIPPED_NO_DATA"


class ReviewTaskStep(StringEnum):
    FREEZE_SOURCES = "FREEZE_SOURCES"
    LOAD_BASE_EVENT = "LOAD_BASE_EVENT"
    EVENT_ORGANIZE = "EVENT_ORGANIZE"
    ANALYSIS_ACTION = "ANALYSIS_ACTION"
    PERSIST_VERSION = "PERSIST_VERSION"


class ReviewDailyDigestStatus(StringEnum):
    EMPTY = "EMPTY"
    EVENT_READY = "EVENT_READY"
    ANALYSIS_READY = "ANALYSIS_READY"
    FAILED = "FAILED"


class ReviewSourceSetStatus(StringEnum):
    BUILDING = "BUILDING"
    READY = "READY"
    ABANDONED = "ABANDONED"


class ReviewSourceType(StringEnum):
    DIARY_EVENT = "DIARY_EVENT"
    SCHEDULE_OCCURRENCE = "SCHEDULE_OCCURRENCE"
    LOWER_REVIEW_EVENT = "LOWER_REVIEW_EVENT"
    LOWER_REVIEW_ANALYSIS = "LOWER_REVIEW_ANALYSIS"
    PRIOR_REVIEW_EVENT = "PRIOR_REVIEW_EVENT"
    USER_FACT_CORRECTION = "USER_FACT_CORRECTION"


class ReviewFactKind(StringEnum):
    USER_FACT = "USER_FACT"
    USER_SELF_REPORT = "USER_SELF_REPORT"
    SCHEDULE_RECORD = "SCHEDULE_RECORD"
    AI_ANALYSIS = "AI_ANALYSIS"
    USER_CORRECTION = "USER_CORRECTION"
    REVIEW_DERIVED = "REVIEW_DERIVED"


class ReviewPeriodRole(StringEnum):
    CURRENT = "CURRENT"
    CONTEXT_ONLY = "CONTEXT_ONLY"
    OUT_OF_PERIOD = "OUT_OF_PERIOD"


class ReviewDependencyType(StringEnum):
    LOWER_PERIOD = "LOWER_PERIOD"
    PRIOR_SAME_LEVEL = "PRIOR_SAME_LEVEL"


class ReviewDependencyStatus(StringEnum):
    AVAILABLE = "AVAILABLE"
    MISSING = "MISSING"
    FAILED = "FAILED"
    SKIPPED_NO_DATA = "SKIPPED_NO_DATA"


class ReviewActionStatus(StringEnum):
    CANDIDATE = "CANDIDATE"
    CONFIRMED = "CONFIRMED"
    IGNORED = "IGNORED"


class ReviewActionCheckStatus(StringEnum):
    FULFILLED = "FULFILLED"
    PARTIALLY_FULFILLED = "PARTIALLY_FULFILLED"
    EXPLICITLY_NOT_FULFILLED = "EXPLICITLY_NOT_FULFILLED"
    NOT_ASSESSABLE = "NOT_ASSESSABLE"


class ReviewDomain(StringEnum):
    WORK_CAREER = "WORK_CAREER"
    HEALTH_WELLBEING = "HEALTH_WELLBEING"
    RELATIONSHIPS_SOCIAL = "RELATIONSHIPS_SOCIAL"
    LEARNING_GROWTH = "LEARNING_GROWTH"
    LIFE_RESOURCES = "LIFE_RESOURCES"
    LEISURE_EXPERIENCE = "LEISURE_EXPERIENCE"


class ReviewAnalysisAngle(StringEnum):
    EMOTION_REGULATION = "EMOTION_REGULATION"
    BEHAVIOR_EXECUTION = "BEHAVIOR_EXECUTION"
    DECISION_PROBLEM_SOLVING = "DECISION_PROBLEM_SOLVING"
    ATTENTION_MOTIVATION_VALUES = "ATTENTION_MOTIVATION_VALUES"
    COGNITION_LEARNING = "COGNITION_LEARNING"
    CAPABILITY_GROWTH = "CAPABILITY_GROWTH"
    RELATIONSHIP_SOCIAL_PSYCHOLOGY = "RELATIONSHIP_SOCIAL_PSYCHOLOGY"


class Review(Base):
    __tablename__ = "reviews"
    __table_args__ = (
        UniqueConstraint(
            "user_id", "review_type", "period_start", "period_end",
            name="uq_reviews_user_type_period",
        ),
        CheckConstraint("period_end >= period_start", name="ck_reviews_period_order"),
        CheckConstraint(
            "review_type IN ('WEEK','MONTH','QUARTER','YEAR')",
            name="ck_reviews_type",
        ),
        Index("ix_reviews_user_period_end", "user_id", text("period_end DESC")),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    review_type = Column(String(16), nullable=False)
    period_start = Column(Date, nullable=False)
    period_end = Column(Date, nullable=False)
    current_version_id = Column(
        UUID(as_uuid=True),
        ForeignKey("review_versions.id", name="fk_reviews_current_version", use_alter=True, ondelete="SET NULL"),
        nullable=True,
    )
    is_unread = Column(Boolean, nullable=False, default=False)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    versions = relationship(
        "ReviewVersion",
        back_populates="review",
        foreign_keys="ReviewVersion.review_id",
        cascade="all, delete-orphan",
    )
    current_version = relationship("ReviewVersion", foreign_keys=[current_version_id], post_update=True)
    tasks = relationship("ReviewTask", back_populates="review", cascade="all, delete-orphan")


class ReviewSourceSet(Base):
    __tablename__ = "review_source_sets"
    __table_args__ = (
        CheckConstraint("status IN ('BUILDING','READY','ABANDONED')", name="ck_review_source_sets_status"),
        Index("ix_review_source_sets_user_created", "user_id", text("created_at DESC")),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    status = Column(String(16), nullable=False, default=ReviewSourceSetStatus.BUILDING.value)
    input_snapshot = Column(JSONB, nullable=False, default=dict)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    items = relationship("ReviewSourceSetItem", back_populates="source_set", cascade="all, delete-orphan")


class ReviewVersion(Base):
    __tablename__ = "review_versions"
    __table_args__ = (
        UniqueConstraint("review_id", "version_no", name="uq_review_versions_number"),
        CheckConstraint("version_no > 0", name="ck_review_versions_positive_number"),
        CheckConstraint(
            "version_type IN ('GENERATED','REGENERATED','EVENT_EDITED','ANALYSIS_UPDATED')",
            name="ck_review_versions_type",
        ),
        Index("ix_review_versions_review_created", "review_id", text("created_at DESC")),
        Index("ix_review_versions_user", "user_id"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    review_id = Column(UUID(as_uuid=True), ForeignKey("reviews.id", ondelete="CASCADE"), nullable=False)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    version_no = Column(Integer, nullable=False)
    version_type = Column(String(24), nullable=False)
    base_version_id = Column(UUID(as_uuid=True), ForeignKey("review_versions.id", ondelete="SET NULL"), nullable=True)
    source_set_id = Column(UUID(as_uuid=True), ForeignKey("review_source_sets.id"), nullable=False)
    event_document = Column(JSONB, nullable=False, default=dict)
    analysis_document = Column(JSONB, nullable=False, default=dict)
    summary = Column(String(120), nullable=False, default="")
    analysis_stale = Column(Boolean, nullable=False, default=False)
    superseded_at_creation = Column(Boolean, nullable=False, default=False)
    missing_periods = Column(JSONB, nullable=False, default=list)
    event_model_info = Column(JSONB, nullable=True)
    analysis_model_info = Column(JSONB, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    review = relationship("Review", back_populates="versions", foreign_keys=[review_id])
    base_version = relationship("ReviewVersion", remote_side=[id], foreign_keys=[base_version_id])
    source_set = relationship("ReviewSourceSet")
    dependencies = relationship(
        "ReviewVersionDependency",
        back_populates="version",
        foreign_keys="ReviewVersionDependency.version_id",
        cascade="all, delete-orphan",
    )
    feedback = relationship("ReviewFeedback", back_populates="version", cascade="all, delete-orphan")
    actions = relationship("ReviewAction", back_populates="version", cascade="all, delete-orphan")
    action_checks = relationship("ReviewActionCheck", back_populates="version", cascade="all, delete-orphan")


class ReviewTask(Base):
    __tablename__ = "review_tasks"
    __table_args__ = (
        CheckConstraint("trigger_type IN ('AUTO','MANUAL','REGENERATE','RETRY')", name="ck_review_tasks_trigger"),
        CheckConstraint("generation_mode IN ('FULL','ANALYSIS_ONLY')", name="ck_review_tasks_mode"),
        CheckConstraint(
            "status IN ('PENDING_START','QUEUED','RUNNING','SUCCEEDED','FAILED','SKIPPED_NO_DATA')",
            name="ck_review_tasks_status",
        ),
        CheckConstraint(
            "current_step IN ('FREEZE_SOURCES','LOAD_BASE_EVENT','EVENT_ORGANIZE','ANALYSIS_ACTION','PERSIST_VERSION')",
            name="ck_review_tasks_step",
        ),
        CheckConstraint(
            "freeze_attempts >= 0 AND event_attempts >= 0 AND analysis_attempts >= 0",
            name="ck_review_tasks_attempts",
        ),
        CheckConstraint(
            "generation_mode <> 'ANALYSIS_ONLY' OR event_attempts = 0",
            name="ck_review_tasks_analysis_only_no_event_attempts",
        ),
        CheckConstraint(
            "NOT source_snapshot_ready OR source_set_id IS NOT NULL",
            name="ck_review_tasks_ready_has_source_set",
        ),
        Index(
            "uq_review_tasks_active_review",
            "review_id",
            unique=True,
            postgresql_where=text("status IN ('PENDING_START','QUEUED','RUNNING')"),
        ),
        Index("ix_review_tasks_user_created", "user_id", text("created_at DESC"), text("id DESC")),
        Index("ix_review_tasks_claim", "status", "available_at", "lease_until"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    review_id = Column(UUID(as_uuid=True), ForeignKey("reviews.id", ondelete="CASCADE"), nullable=False)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    trigger_type = Column(String(16), nullable=False)
    generation_mode = Column(String(20), nullable=False, default=ReviewGenerationMode.FULL.value)
    base_version_id = Column(UUID(as_uuid=True), ForeignKey("review_versions.id", ondelete="SET NULL"), nullable=True)
    retry_of_task_id = Column(UUID(as_uuid=True), ForeignKey("review_tasks.id", ondelete="SET NULL"), nullable=True)
    source_set_id = Column(UUID(as_uuid=True), ForeignKey("review_source_sets.id"), nullable=True)
    status = Column(String(24), nullable=False, default=ReviewTaskStatus.QUEUED.value)
    current_step = Column(String(24), nullable=False, default=ReviewTaskStep.FREEZE_SOURCES.value)
    freeze_attempts = Column(Integer, nullable=False, default=0)
    event_attempts = Column(Integer, nullable=False, default=0)
    analysis_attempts = Column(Integer, nullable=False, default=0)
    available_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    lease_until = Column(DateTime, nullable=True)
    run_token = Column(UUID(as_uuid=True), nullable=True)
    source_snapshot_ready = Column(Boolean, nullable=False, default=False)
    event_result = Column(JSONB, nullable=True)
    analysis_result = Column(JSONB, nullable=True)
    error_code = Column(String(64), nullable=True)
    error_message = Column(Text, nullable=True)
    requested_start_at = Column(DateTime, nullable=True)
    started_by_user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    started_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)
    result_version_id = Column(UUID(as_uuid=True), ForeignKey("review_versions.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    review = relationship("Review", back_populates="tasks")
    base_version = relationship("ReviewVersion", foreign_keys=[base_version_id])
    retry_of_task = relationship("ReviewTask", remote_side=[id], foreign_keys=[retry_of_task_id])
    source_set = relationship("ReviewSourceSet")
    result_version = relationship("ReviewVersion", foreign_keys=[result_version_id])


class ReviewDailyDigest(Base):
    __tablename__ = "review_daily_digests"
    __table_args__ = (
        UniqueConstraint("review_task_id", "digest_date", name="uq_review_daily_digests_task_date"),
        CheckConstraint("status IN ('EMPTY','EVENT_READY','ANALYSIS_READY','FAILED')", name="ck_review_daily_digests_status"),
        Index("ix_review_daily_digests_version", "review_version_id", "digest_date"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    review_task_id = Column(UUID(as_uuid=True), ForeignKey("review_tasks.id", ondelete="CASCADE"), nullable=False)
    review_version_id = Column(UUID(as_uuid=True), ForeignKey("review_versions.id", ondelete="SET NULL"), nullable=True)
    source_set_id = Column(UUID(as_uuid=True), ForeignKey("review_source_sets.id"), nullable=False)
    digest_date = Column(Date, nullable=False)
    status = Column(String(24), nullable=False, default=ReviewDailyDigestStatus.EMPTY.value)
    event_document = Column(JSONB, nullable=False, default=dict)
    analysis_document = Column(JSONB, nullable=False, default=dict)
    event_model_info = Column(JSONB, nullable=True)
    analysis_model_info = Column(JSONB, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    task = relationship("ReviewTask")
    version = relationship("ReviewVersion")
    source_set = relationship("ReviewSourceSet")


class ReviewSource(Base):
    __tablename__ = "review_sources"
    __table_args__ = (
        CheckConstraint(
            "source_type IN ('DIARY_EVENT','SCHEDULE_OCCURRENCE','LOWER_REVIEW_EVENT',"
            "'LOWER_REVIEW_ANALYSIS','PRIOR_REVIEW_EVENT','USER_FACT_CORRECTION')",
            name="ck_review_sources_type",
        ),
        CheckConstraint(
            "fact_kind IN ('USER_FACT','USER_SELF_REPORT','SCHEDULE_RECORD','AI_ANALYSIS','USER_CORRECTION','REVIEW_DERIVED')",
            name="ck_review_sources_fact_kind",
        ),
        CheckConstraint(
            "period_role IN ('CURRENT','CONTEXT_ONLY','OUT_OF_PERIOD')",
            name="ck_review_sources_period_role",
        ),
        CheckConstraint(
            "relative_position IS NULL OR relative_position IN ('BEFORE','AFTER')",
            name="ck_review_sources_relative_position",
        ),
        CheckConstraint(
            "(period_role = 'CURRENT' AND relative_position IS NULL) OR "
            "(period_role <> 'CURRENT' AND relative_position IS NOT NULL)",
            name="ck_review_sources_period_position",
        ),
        Index("ix_review_sources_user_root_fact", "user_id", "root_fact_id"),
        Index("ix_review_sources_origin_version", "origin_review_version_id"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    root_fact_id = Column(String(200), nullable=False)
    source_type = Column(String(32), nullable=False)
    root_source_type = Column(String(32), nullable=False)
    fact_kind = Column(String(24), nullable=False)
    source_date = Column(Date, nullable=False)
    period_role = Column(String(20), nullable=False)
    relative_position = Column(String(8), nullable=True)
    origin_review_id = Column(UUID(as_uuid=True), ForeignKey("reviews.id", ondelete="SET NULL"), nullable=True)
    origin_review_version_id = Column(UUID(as_uuid=True), ForeignKey("review_versions.id", ondelete="SET NULL"), nullable=True)
    origin_content_item_type = Column(String(32), nullable=True)
    origin_content_item_id = Column(UUID(as_uuid=True), nullable=True)
    origin_content_item_key = Column(String(200), nullable=True)
    lineage = Column(JSONB, nullable=False, default=list)
    content = Column(Text, nullable=False)
    snapshot = Column(JSONB, nullable=False, default=dict)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    source_sets = relationship("ReviewSourceSetItem", back_populates="source", cascade="all, delete-orphan")


class ReviewSourceSetItem(Base):
    __tablename__ = "review_source_set_items"
    __table_args__ = (
        Index("ix_review_source_set_items_source", "source_id"),
    )

    source_set_id = Column(
        UUID(as_uuid=True),
        ForeignKey("review_source_sets.id", ondelete="CASCADE"),
        primary_key=True,
    )
    source_id = Column(
        UUID(as_uuid=True),
        ForeignKey("review_sources.id", ondelete="RESTRICT"),
        primary_key=True,
    )

    source_set = relationship("ReviewSourceSet", back_populates="items")
    source = relationship("ReviewSource", back_populates="source_sets")


class ReviewVersionDependency(Base):
    __tablename__ = "review_version_dependencies"
    __table_args__ = (
        UniqueConstraint(
            "version_id", "dependency_type", "period_start", "period_end",
            name="uq_review_dependencies_period",
        ),
        CheckConstraint(
            "dependency_type IN ('LOWER_PERIOD','PRIOR_SAME_LEVEL')",
            name="ck_review_dependencies_type",
        ),
        CheckConstraint(
            "status IN ('AVAILABLE','MISSING','FAILED','SKIPPED_NO_DATA')",
            name="ck_review_dependencies_status",
        ),
        CheckConstraint("period_end >= period_start", name="ck_review_dependencies_period_order"),
        CheckConstraint(
            "status <> 'AVAILABLE' OR dependency_version_id IS NOT NULL",
            name="ck_review_dependencies_available_version",
        ),
        Index("ix_review_dependencies_dependency_review", "dependency_review_id"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    version_id = Column(UUID(as_uuid=True), ForeignKey("review_versions.id", ondelete="CASCADE"), nullable=False)
    dependency_type = Column(String(24), nullable=False)
    dependency_review_id = Column(UUID(as_uuid=True), ForeignKey("reviews.id", ondelete="SET NULL"), nullable=True)
    dependency_version_id = Column(UUID(as_uuid=True), ForeignKey("review_versions.id", ondelete="SET NULL"), nullable=True)
    period_start = Column(Date, nullable=False)
    period_end = Column(Date, nullable=False)
    status = Column(String(24), nullable=False)
    context_only = Column(Boolean, nullable=False, default=False)

    version = relationship("ReviewVersion", back_populates="dependencies", foreign_keys=[version_id])
    dependency_version = relationship("ReviewVersion", foreign_keys=[dependency_version_id])


class ReviewFeedback(Base):
    __tablename__ = "review_feedback"
    __table_args__ = (
        UniqueConstraint("version_id", "analysis_item_id", name="uq_review_feedback_analysis_item"),
        CheckConstraint("rating IS NULL OR (rating >= 1 AND rating <= 5)", name="ck_review_feedback_rating"),
        CheckConstraint(
            "rating IS NOT NULL OR NULLIF(BTRIM(comment), '') IS NOT NULL",
            name="ck_review_feedback_has_content",
        ),
        CheckConstraint(
            "angle_code IN ('EMOTION_REGULATION','BEHAVIOR_EXECUTION','DECISION_PROBLEM_SOLVING',"
            "'ATTENTION_MOTIVATION_VALUES','COGNITION_LEARNING','CAPABILITY_GROWTH',"
            "'RELATIONSHIP_SOCIAL_PSYCHOLOGY')",
            name="ck_review_feedback_angle",
        ),
        Index("ix_review_feedback_user", "user_id"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    version_id = Column(UUID(as_uuid=True), ForeignKey("review_versions.id", ondelete="CASCADE"), nullable=False)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    analysis_item_id = Column(UUID(as_uuid=True), nullable=False)
    angle_code = Column(String(40), nullable=False)
    rating = Column(Integer, nullable=True)
    comment = Column(Text, nullable=True)
    is_inherited = Column(Boolean, nullable=False, default=False)
    source_feedback_id = Column(UUID(as_uuid=True), ForeignKey("review_feedback.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    version = relationship("ReviewVersion", back_populates="feedback")
    source_feedback = relationship("ReviewFeedback", remote_side=[id])


class ReviewAction(Base):
    __tablename__ = "review_actions"
    __table_args__ = (
        CheckConstraint("status IN ('CANDIDATE','CONFIRMED','IGNORED')", name="ck_review_actions_status"),
        CheckConstraint(
            "primary_domain IN ('WORK_CAREER','HEALTH_WELLBEING','RELATIONSHIPS_SOCIAL',"
            "'LEARNING_GROWTH','LIFE_RESOURCES','LEISURE_EXPERIENCE')",
            name="ck_review_actions_domain",
        ),
        Index("ix_review_actions_version_domain", "version_id", "primary_domain"),
        Index("ix_review_actions_source", "source_action_id"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    version_id = Column(UUID(as_uuid=True), ForeignKey("review_versions.id", ondelete="CASCADE"), nullable=False)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    primary_domain = Column(String(32), nullable=False)
    related_domains = Column(JSONB, nullable=False, default=list)
    content = Column(Text, nullable=False)
    edited_content = Column(Text, nullable=True)
    rationale = Column(Text, nullable=True)
    status = Column(String(16), nullable=False, default=ReviewActionStatus.CANDIDATE.value)
    source_action_id = Column(UUID(as_uuid=True), ForeignKey("review_actions.id", ondelete="SET NULL"), nullable=True)
    is_inherited = Column(Boolean, nullable=False, default=False)
    basis_analysis_ids = Column(JSONB, nullable=False, default=list)
    basis_source_ids = Column(JSONB, nullable=False, default=list)
    verification_rule = Column(JSONB, nullable=False, default=dict)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    version = relationship("ReviewVersion", back_populates="actions")
    source_action = relationship("ReviewAction", remote_side=[id])


class ReviewActionCheck(Base):
    __tablename__ = "review_action_checks"
    __table_args__ = (
        UniqueConstraint("version_id", "previous_action_id", name="uq_review_action_checks_previous_action"),
        CheckConstraint(
            "check_status IN ('FULFILLED','PARTIALLY_FULFILLED','EXPLICITLY_NOT_FULFILLED','NOT_ASSESSABLE')",
            name="ck_review_action_checks_status",
        ),
        Index("ix_review_action_checks_user", "user_id"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    version_id = Column(UUID(as_uuid=True), ForeignKey("review_versions.id", ondelete="CASCADE"), nullable=False)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    previous_action_id = Column(UUID(as_uuid=True), ForeignKey("review_actions.id", ondelete="RESTRICT"), nullable=False)
    check_status = Column(String(32), nullable=False)
    explanation = Column(Text, nullable=False)
    evidence_source_ids = Column(JSONB, nullable=False, default=list)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    version = relationship("ReviewVersion", back_populates="action_checks")
    previous_action = relationship("ReviewAction")
