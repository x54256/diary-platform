"""日记数据模型"""

import enum
import uuid
from datetime import datetime

from sqlalchemy import Column, String, Text, Date, DateTime, Enum, ForeignKey, Integer, Boolean, Index, text, Time
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import relationship

from database import Base


class DiaryStatus(enum.Enum):
    """日记状态枚举"""

    saved = "saved"          # 已保存
    organized = "organized"  # 已整理
    analyzed = "analyzed"    # 已分析


class Diary(Base):
    """日记表"""

    __tablename__ = "diaries"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    original_text = Column(Text, nullable=False)
    diary_date = Column(Date, nullable=False)
    status = Column(Enum(DiaryStatus), default=DiaryStatus.saved)
    is_dirty = Column(Boolean, default=False, nullable=False)
    # 原文变更时递增；整理结果只有在修订号一致时才可作为回顾来源。
    content_revision = Column(Integer, default=1, nullable=False)
    deleted_at = Column(DateTime, nullable=True)
    deleted_by = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # 关系映射
    user = relationship("User", back_populates="diaries", foreign_keys=[user_id])
    # 1:1 关系，日记整理内容
    organized = relationship(
        "DiaryOrganized",
        back_populates="diary",
        uselist=False,
        cascade="all, delete-orphan",
    )
    # M:N 关系，日记标签
    tags = relationship("Tag", secondary="diary_tags", back_populates="diaries")
    # 历史分析轮次（1:N）
    analysis_runs = relationship("AnalysisRun", back_populates="diary", cascade="all, delete-orphan")
    action_items = relationship("DiaryActionItem", back_populates="diary", cascade="all, delete-orphan")
    favorites = relationship("Favorite", back_populates="diary", cascade="all, delete-orphan")


class DiaryOrganized(Base):
    """日记整理内容表（与 diaries 表 1:1 关系）"""

    __tablename__ = "diary_organized"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    task_id = Column(UUID(as_uuid=True), ForeignKey("organize_tasks.id"), nullable=False)
    diary_id = Column(
        UUID(as_uuid=True), ForeignKey("diaries.id"), unique=True, nullable=False
    )
    source_content_revision = Column(Integer, default=1, nullable=False)
    # 结构化事件被重新产生或编辑时递增。
    structured_revision = Column(Integer, default=1, nullable=False)
    title = Column(String(200))
    summary = Column(Text)
    content = Column(Text)
    mood = Column(String(50))
    location = Column(String(100))
    introduction = Column(Text)       # 引入段
    trivia = Column(Text)             # JSON 序列化的琐事数组
    plans = Column(Text)              # JSON 序列化的计划数组
    organized_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # 关系映射
    diary = relationship("Diary", back_populates="organized")
    # 结构化事件（1:N）
    events = relationship("DiaryEvent", back_populates="organized", cascade="all, delete-orphan", order_by="DiaryEvent.sort_order")
    # 内容检查记录（1:N）
    check_logs = relationship("DiaryCheckLog", back_populates="organized", cascade="all, delete-orphan", order_by="DiaryCheckLog.sort_order")
    # 清洗审核日志（1:N）
    clean_check_logs = relationship("DiaryCleanCheckLog", back_populates="organized", cascade="all, delete-orphan", order_by="DiaryCleanCheckLog.sort_order")

class AnalysisRun(Base):
    """一次完整分析结果，支持历史版本"""

    __tablename__ = "analysis_runs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    diary_id = Column(UUID(as_uuid=True), ForeignKey("diaries.id"), nullable=False)
    diary_organized_id = Column(UUID(as_uuid=True), ForeignKey("diary_organized.id"), nullable=False)
    source_structured_revision = Column(Integer, default=1, nullable=False)
    task_id = Column(UUID(as_uuid=True), ForeignKey("organize_tasks.id"), nullable=True)
    mood = Column(String(50), nullable=True)
    status = Column(String(20), default="CURRENT", nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    diary = relationship("Diary", back_populates="analysis_runs")
    organized = relationship("DiaryOrganized")
    items = relationship(
        "AnalysisItem",
        back_populates="analysis_run",
        cascade="all, delete-orphan",
        order_by="AnalysisItem.sort_order",
    )
    feedbacks = relationship("AnalysisFeedback", back_populates="analysis_run", cascade="all, delete-orphan")


class AnalysisItem(Base):
    """分析轮次中的一条分析内容"""

    __tablename__ = "analysis_items"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    analysis_run_id = Column(UUID(as_uuid=True), ForeignKey("analysis_runs.id"), nullable=False)
    scope = Column(String(20), nullable=False)  # DIARY / EVENT
    event_id = Column(UUID(as_uuid=True), ForeignKey("diary_events.id"), nullable=True)
    analysis_type = Column(String(50), nullable=False)
    content = Column(Text, nullable=False)
    question = Column(Text, nullable=True)
    sort_order = Column(Integer, default=0, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    analysis_run = relationship("AnalysisRun", back_populates="items")
    event = relationship("DiaryEvent")


class AnalysisFeedback(Base):
    """用户对某个分析类型块的反馈"""

    __tablename__ = "analysis_feedback"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    analysis_run_id = Column(UUID(as_uuid=True), ForeignKey("analysis_runs.id"), nullable=False)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    scope = Column(String(20), nullable=False)  # DIARY / EVENT
    event_id = Column(UUID(as_uuid=True), ForeignKey("diary_events.id"), nullable=True)
    analysis_type = Column(String(50), nullable=False)
    rating = Column(Integer, nullable=False)
    comment = Column(Text, nullable=True)
    is_inherited = Column(Boolean, default=False, nullable=False)
    source_feedback_id = Column(UUID(as_uuid=True), ForeignKey("analysis_feedback.id"), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    analysis_run = relationship("AnalysisRun", back_populates="feedbacks")
    user = relationship("User")
    event = relationship("DiaryEvent")
    source_feedback = relationship("AnalysisFeedback", remote_side=[id])


class DiaryActionItem(Base):
    """日记详情中的独立行动项。"""

    __tablename__ = "diary_action_items"
    __table_args__ = (
        Index("ix_diary_action_items_diary_status", "diary_id", "status"),
        Index("ix_diary_action_items_user_diary", "user_id", "diary_id"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    diary_id = Column(UUID(as_uuid=True), ForeignKey("diaries.id", ondelete="CASCADE"), nullable=False)
    generation_run_id = Column(UUID(as_uuid=True), ForeignKey("analysis_runs.id"), nullable=False)
    source_kind = Column(String(20), nullable=False)  # PLAN / SUGGESTION / MERGED
    source_refs = Column(JSONB, nullable=False, default=dict)
    title = Column(String(200), nullable=False)
    is_all_day = Column(Boolean, nullable=False, default=True)
    start_date = Column(Date, nullable=False)
    start_time = Column(Time, nullable=True)
    end_time = Column(Time, nullable=True)
    recurrence_type = Column(String(32), nullable=False, default="NONE")
    interval = Column(Integer, nullable=False, default=1)
    weekdays = Column(JSONB, nullable=False, default=list)
    month_day = Column(Integer, nullable=True)
    recurrence_month = Column(Integer, nullable=True)
    nth_week = Column(Integer, nullable=True)
    nth_weekday = Column(Integer, nullable=True)
    recurrence_until = Column(Date, nullable=True)
    recurrence_count = Column(Integer, nullable=True)
    status = Column(String(20), nullable=False, default="pending")
    completed_at = Column(DateTime, nullable=True)
    user_modified = Column(Boolean, nullable=False, default=False)
    sort_order = Column(Integer, nullable=False, default=0)
    deleted_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    diary = relationship("Diary", back_populates="action_items")
    generation_run = relationship("AnalysisRun")
    schedule_links = relationship(
        "DiaryActionScheduleLink",
        back_populates="action_item",
        cascade="all, delete-orphan",
        order_by="DiaryActionScheduleLink.linked_at",
    )


class DiaryActionScheduleLink(Base):
    """行动项与日程任务的当前及历史关联。"""

    __tablename__ = "diary_action_schedule_links"
    __table_args__ = (
        Index(
            "uq_diary_action_active_link",
            "action_item_id",
            unique=True,
            postgresql_where=text("unlinked_at IS NULL"),
        ),
        Index(
            "uq_schedule_active_action_link",
            "schedule_task_id",
            unique=True,
            postgresql_where=text("unlinked_at IS NULL AND schedule_task_id IS NOT NULL"),
        ),
        Index("ix_diary_action_links_schedule_task", "schedule_task_id"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    action_item_id = Column(UUID(as_uuid=True), ForeignKey("diary_action_items.id", ondelete="CASCADE"), nullable=False)
    schedule_task_id = Column(UUID(as_uuid=True), ForeignKey("schedule_tasks.id", ondelete="SET NULL"), nullable=True)
    schedule_task_snapshot_id = Column(UUID(as_uuid=True), nullable=False)
    completion_occurrence_id = Column(UUID(as_uuid=True), ForeignKey("schedule_occurrences.id", ondelete="SET NULL"), nullable=True)
    linked_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    unlinked_at = Column(DateTime, nullable=True)
    unlink_reason = Column(String(32), nullable=True)

    action_item = relationship("DiaryActionItem", back_populates="schedule_links")
    schedule_task = relationship("ScheduleTask", foreign_keys=[schedule_task_id])
    completion_occurrence = relationship("ScheduleOccurrence", foreign_keys=[completion_occurrence_id])


class DiaryEvent(Base):
    """日记事件表（结构化日记的每个事件）"""

    __tablename__ = "diary_events"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    diary_organized_id = Column(UUID(as_uuid=True), ForeignKey("diary_organized.id"), nullable=False)
    event_title = Column(String(200))
    body = Column(Text, nullable=False)
    feeling = Column(Text, nullable=True)
    reflection = Column(Text, nullable=True)
    event_tags = Column(Text)        # JSON: {"domain":[], "topic":[], "person_object":[], "psychological":[], "knowledge":[]}
    sort_order = Column(Integer, default=0)
    ai_importance = Column(String(8), nullable=True)
    ai_importance_reason = Column(Text, nullable=True)
    user_importance = Column(String(8), nullable=True)
    user_importance_reason = Column(Text, nullable=True)
    importance_origin = Column(String(24), nullable=True)
    importance_updated_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    # 关系映射
    organized = relationship("DiaryOrganized", back_populates="events")
    # M:N 关系，事件标签
    tags = relationship("Tag", secondary="event_tags", back_populates="events")
    favorites = relationship("Favorite", back_populates="event", cascade="all, delete-orphan")


class DiaryAnnotation(Base):
    """日记内容划线批注的定位信息。"""

    __tablename__ = "diary_annotations"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    diary_id = Column(UUID(as_uuid=True), ForeignKey("diaries.id"), nullable=False)
    target_type = Column(String(30), nullable=False)
    event_id = Column(UUID(as_uuid=True), ForeignKey("diary_events.id"), nullable=True)
    field_name = Column(String(30), nullable=True)
    analysis_item_id = Column(UUID(as_uuid=True), ForeignKey("analysis_items.id"), nullable=True)
    start_paragraph = Column(Integer, nullable=False, default=0)
    start_offset = Column(Integer, nullable=False)
    end_paragraph = Column(Integer, nullable=False, default=0)
    end_offset = Column(Integer, nullable=False)
    selected_text = Column(Text, nullable=False)
    context_before = Column(Text, nullable=True)
    context_after = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    deleted_at = Column(DateTime, nullable=True)
    deleted_by = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    deleted_reason = Column(String(30), nullable=True)
    merged_into_id = Column(UUID(as_uuid=True), ForeignKey("diary_annotations.id"), nullable=True)

    diary = relationship("Diary")
    event = relationship("DiaryEvent")
    analysis_item = relationship("AnalysisItem")
    comments = relationship("DiaryAnnotationComment", back_populates="annotation")
    merged_into = relationship("DiaryAnnotation", remote_side=[id], uselist=False)


class DiaryAnnotationComment(Base):
    """日记划线对应的单条评论。"""

    __tablename__ = "diary_annotation_comments"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    annotation_id = Column(UUID(as_uuid=True), ForeignKey("diary_annotations.id"), nullable=False)
    content = Column(Text, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    deleted_at = Column(DateTime, nullable=True)
    deleted_by = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    deleted_reason = Column(String(30), nullable=True)

    annotation = relationship("DiaryAnnotation", back_populates="comments")


class DiaryCheckLog(Base):
    """内容检查记录表（内部保留，用户不可见）"""

    __tablename__ = "diary_check_logs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    diary_organized_id = Column(UUID(as_uuid=True), ForeignKey("diary_organized.id"), nullable=False)
    check_item = Column(String(100))
    status = Column(String(20))  # "通过" 或 "已修正"
    issue = Column(Text)
    before = Column(Text)
    after = Column(Text)
    target = Column(String(200))
    reason = Column(Text)
    sort_order = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.utcnow)

    # 关系映射
    organized = relationship("DiaryOrganized", back_populates="check_logs")


class DiaryCleanCheckLog(Base):
    """清洗审核日志表（内部保留，用户不可见）"""

    __tablename__ = "diary_clean_check_logs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    diary_organized_id = Column(UUID(as_uuid=True), ForeignKey("diary_organized.id"), nullable=False)
    issue = Column(Text)
    before = Column(Text)
    after = Column(Text)
    reason = Column(Text)
    sort_order = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.utcnow)

    # 关系映射
    organized = relationship("DiaryOrganized", back_populates="clean_check_logs")


class OrganizeTask(Base):
    """异步整理任务表"""

    __tablename__ = "organize_tasks"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    diary_id = Column(UUID(as_uuid=True), ForeignKey("diaries.id"), nullable=False)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    status = Column(String(20), default="running")  # running / completed / failed
    task_type = Column(String(20), default="organize")  # organize（整理）/ analyze（分析）
    analysis_mode = Column(String(20), nullable=True)  # ordinary（普通分析）/ feedback（反馈分析）
    current_step = Column(String(50), nullable=True)  # text_cleaning / clean_checking / event_organizing / structuring / content_checking
    error_message = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
