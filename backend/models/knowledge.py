"""知识沉淀任务、成功记录与知识事件模型。"""

import enum
import uuid
from datetime import datetime

from sqlalchemy import Boolean, CheckConstraint, Column, Date, DateTime, ForeignKey, Index, Integer, String, Text, Time, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from pgvector.sqlalchemy import Vector

from database import Base
from services.task_environment import TASK_ENVIRONMENT


class StringEnum(str, enum.Enum):
    pass


class KnowledgeTaskStatus(StringEnum):
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"


class KnowledgeTaskStep(StringEnum):
    VALIDATE_SOURCE = "VALIDATE_SOURCE"
    PREPARE_BATCHES = "PREPARE_BATCHES"
    EXTRACT_BATCH = "EXTRACT_BATCH"
    PREPARE_REVIEW_BATCHES = "PREPARE_REVIEW_BATCHES"
    REVIEW_BATCH = "REVIEW_BATCH"
    PUBLISH = "PUBLISH"
    MATCH_MATTERS = "MATCH_MATTERS"


class KnowledgeTask(Base):
    __tablename__ = "knowledge_tasks"
    __table_args__ = (
        CheckConstraint("status IN ('QUEUED','RUNNING','SUCCEEDED','FAILED')", name="ck_knowledge_tasks_status"),
        CheckConstraint(
            "current_step IS NULL OR current_step IN ('VALIDATE_SOURCE','PREPARE_BATCHES','EXTRACT_BATCH','PREPARE_REVIEW_BATCHES','REVIEW_BATCH','PUBLISH','MATCH_MATTERS')",
            name="ck_knowledge_tasks_step",
        ),
        CheckConstraint("task_type IN ('DEPOSIT','UPGRADE')", name="ck_knowledge_tasks_type"),
        CheckConstraint("retry_count >= 0", name="ck_knowledge_tasks_retry_count"),
        Index(
            "uq_knowledge_tasks_user_active", "environment", "user_id", unique=True,
            postgresql_where=text("status IN ('QUEUED','RUNNING')"),
        ),
        Index(
            "uq_knowledge_tasks_source_active", "environment", "diary_id", "source_structured_revision",
            unique=True, postgresql_where=text("status IN ('QUEUED','RUNNING')"),
        ),
        Index("ix_knowledge_tasks_queue", "status", "available_at", "created_at"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    environment = Column(String(32), nullable=False, default=TASK_ENVIRONMENT)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    diary_id = Column(UUID(as_uuid=True), ForeignKey("diaries.id", ondelete="RESTRICT"), nullable=False)
    source_diary_organized_id = Column(UUID(as_uuid=True), ForeignKey("diary_organized.id", ondelete="RESTRICT"), nullable=False)
    source_structured_revision = Column(Integer, nullable=False)
    # DEPOSIT 沉淀任务（走完整图）；UPGRADE 升级任务（不走图，直接执行事项匹配）。
    task_type = Column(String(16), nullable=False, default="DEPOSIT")
    status = Column(String(16), nullable=False, default=KnowledgeTaskStatus.QUEUED.value)
    current_step = Column(String(32), nullable=True)
    retry_count = Column(Integer, nullable=False, default=0)
    available_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    lease_until = Column(DateTime, nullable=True)
    run_token = Column(UUID(as_uuid=True), nullable=True)
    error_code = Column(String(64), nullable=True)
    error_message = Column(Text, nullable=True)
    checkpoint_cleaned_at = Column(DateTime, nullable=True)
    started_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)


class KnowledgeDeposit(Base):
    __tablename__ = "knowledge_deposits"
    __table_args__ = (
        CheckConstraint("completed_stage IN ('ATOMIC_EVENTS','MATTERS')", name="ck_knowledge_deposits_stage"),
        UniqueConstraint("task_id", name="uq_knowledge_deposits_task"),
        Index("ix_knowledge_deposits_user", "user_id", "deposited_at"),
    )

    diary_id = Column(UUID(as_uuid=True), ForeignKey("diaries.id", ondelete="RESTRICT"), primary_key=True)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    task_id = Column(UUID(as_uuid=True), ForeignKey("knowledge_tasks.id", ondelete="RESTRICT"), nullable=False)
    source_diary_organized_id = Column(UUID(as_uuid=True), ForeignKey("diary_organized.id", ondelete="RESTRICT"), nullable=False)
    source_structured_revision = Column(Integer, nullable=False)
    completed_stage = Column(String(32), nullable=False, default="ATOMIC_EVENTS")
    deposited_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)


class KnowledgeAtomicEvent(Base):
    __tablename__ = "knowledge_atomic_events"
    __table_args__ = (
        CheckConstraint("source_order >= 0", name="ck_knowledge_atomic_events_source_order"),
        CheckConstraint("char_length(title) BETWEEN 1 AND 20", name="ck_knowledge_atomic_events_title"),
        CheckConstraint(
            "jsonb_typeof(content) = 'array' AND jsonb_array_length(content) > 0",
            name="ck_knowledge_atomic_events_content",
        ),
        UniqueConstraint("user_id", "diary_id", "source_diary_event_id", "source_order", name="uq_knowledge_atomic_events_source_order"),
        Index(
            "ix_knowledge_atomic_events_user_time", "user_id", text("occurred_on DESC"),
            text("occurred_time DESC NULLS LAST"), text("created_at DESC"), text("id DESC"),
        ),
        Index(
            "ix_knowledge_atomic_events_matter_time", "matter_id", text("occurred_on DESC"),
            text("occurred_time DESC NULLS LAST"), text("id DESC"),
        ),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    diary_id = Column(UUID(as_uuid=True), ForeignKey("knowledge_deposits.diary_id", ondelete="RESTRICT"), nullable=False)
    source_diary_event_id = Column(UUID(as_uuid=True), ForeignKey("diary_events.id", ondelete="RESTRICT"), nullable=False)
    source_order = Column(Integer, nullable=False)
    title = Column(String(20), nullable=False)
    content = Column(JSONB, nullable=False)
    occurred_on = Column(Date, nullable=False)
    occurred_time = Column(Time, nullable=True)
    # 事项归属与语义向量均可空：存量事件与匹配失败事件不参与召回、不进入事项。
    matter_id = Column(UUID(as_uuid=True), ForeignKey("knowledge_matters.id", ondelete="RESTRICT"), nullable=True)
    embedding = Column(Vector(1024), nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)


class KnowledgeMatterStatus(StringEnum):
    ONGOING = "ONGOING"
    ENDED = "ENDED"
    PAUSED = "PAUSED"


class KnowledgeMatter(Base):
    __tablename__ = "knowledge_matters"
    __table_args__ = (
        CheckConstraint("status IN ('ONGOING','ENDED','PAUSED')", name="ck_knowledge_matters_status"),
        CheckConstraint("char_length(name) BETWEEN 1 AND 30", name="ck_knowledge_matters_name"),
        CheckConstraint("event_count >= 1", name="ck_knowledge_matters_event_count"),
        CheckConstraint("started_on <= last_event_on", name="ck_knowledge_matters_dates"),
        Index(
            "ix_knowledge_matters_user_time", "user_id", text("last_event_on DESC"),
            text("updated_at DESC"), text("id DESC"),
        ),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    name = Column(String(30), nullable=False)
    overview = Column(Text, nullable=False)
    status = Column(String(16), nullable=False, default=KnowledgeMatterStatus.ONGOING.value)
    started_on = Column(Date, nullable=False)
    last_event_on = Column(Date, nullable=False)
    event_count = Column(Integer, nullable=False, default=1)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)


class KnowledgeEventReview(Base):
    __tablename__ = "knowledge_event_reviews"
    __table_args__ = (
        CheckConstraint("jsonb_typeof(issues) = 'array'", name="ck_knowledge_event_reviews_issues"),
        UniqueConstraint("knowledge_event_id", name="uq_knowledge_event_reviews_event"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    knowledge_event_id = Column(
        UUID(as_uuid=True),
        ForeignKey("knowledge_atomic_events.id", ondelete="CASCADE"),
        nullable=False,
    )
    task_id = Column(UUID(as_uuid=True), ForeignKey("knowledge_tasks.id", ondelete="RESTRICT"), nullable=False)
    issues = Column(JSONB, nullable=False, default=list)
    content_changed = Column(Boolean, nullable=False, default=False)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
