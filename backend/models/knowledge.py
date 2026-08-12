"""知识沉淀任务、成功记录与原子事件模型。"""

import enum
import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, Column, Date, DateTime, ForeignKey, Index, Integer, String, Text, Time, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import JSONB, UUID

from database import Base


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
    PUBLISH = "PUBLISH"


class KnowledgeTask(Base):
    __tablename__ = "knowledge_tasks"
    __table_args__ = (
        CheckConstraint("status IN ('QUEUED','RUNNING','SUCCEEDED','FAILED')", name="ck_knowledge_tasks_status"),
        CheckConstraint(
            "current_step IS NULL OR current_step IN ('VALIDATE_SOURCE','PREPARE_BATCHES','EXTRACT_BATCH','PUBLISH')",
            name="ck_knowledge_tasks_step",
        ),
        CheckConstraint("retry_count >= 0", name="ck_knowledge_tasks_retry_count"),
        Index(
            "uq_knowledge_tasks_user_active", "user_id", unique=True,
            postgresql_where=text("status IN ('QUEUED','RUNNING')"),
        ),
        Index(
            "uq_knowledge_tasks_source_active", "diary_id", "source_structured_revision",
            unique=True, postgresql_where=text("status IN ('QUEUED','RUNNING')"),
        ),
        Index("ix_knowledge_tasks_queue", "status", "available_at", "created_at"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    diary_id = Column(UUID(as_uuid=True), ForeignKey("diaries.id", ondelete="RESTRICT"), nullable=False)
    source_diary_organized_id = Column(UUID(as_uuid=True), ForeignKey("diary_organized.id", ondelete="RESTRICT"), nullable=False)
    source_structured_revision = Column(Integer, nullable=False)
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
        CheckConstraint("completed_stage = 'ATOMIC_EVENTS'", name="ck_knowledge_deposits_stage"),
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
        CheckConstraint("jsonb_typeof(source_fragments) = 'array'", name="ck_knowledge_atomic_events_fragments"),
        UniqueConstraint("user_id", "diary_id", "source_diary_event_id", "source_order", name="uq_knowledge_atomic_events_source_order"),
        Index(
            "ix_knowledge_atomic_events_user_time", "user_id", text("occurred_on DESC"),
            text("occurred_time DESC NULLS LAST"), text("created_at DESC"), text("id DESC"),
        ),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    diary_id = Column(UUID(as_uuid=True), ForeignKey("knowledge_deposits.diary_id", ondelete="RESTRICT"), nullable=False)
    source_diary_event_id = Column(UUID(as_uuid=True), ForeignKey("diary_events.id", ondelete="RESTRICT"), nullable=False)
    source_order = Column(Integer, nullable=False)
    title = Column(String(20), nullable=False)
    source_fragments = Column(JSONB, nullable=False)
    content = Column(Text, nullable=False)
    occurred_on = Column(Date, nullable=False)
    occurred_time = Column(Time, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
