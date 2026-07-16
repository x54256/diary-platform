"""日记数据模型"""

import enum
import uuid
from datetime import datetime

from sqlalchemy import Column, String, Text, Date, DateTime, Enum, ForeignKey, Integer, Boolean
from sqlalchemy.dialects.postgresql import UUID
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


class DiaryOrganized(Base):
    """日记整理内容表（与 diaries 表 1:1 关系）"""

    __tablename__ = "diary_organized"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    task_id = Column(UUID(as_uuid=True), ForeignKey("organize_tasks.id"), nullable=False)
    diary_id = Column(
        UUID(as_uuid=True), ForeignKey("diaries.id"), unique=True, nullable=False
    )
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
    created_at = Column(DateTime, default=datetime.utcnow)

    # 关系映射
    organized = relationship("DiaryOrganized", back_populates="events")
    # M:N 关系，事件标签
    tags = relationship("Tag", secondary="event_tags", back_populates="events")


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
    current_step = Column(String(50), nullable=True)  # text_cleaning / clean_checking / event_organizing / structuring / content_checking / metadata_extracting
    error_message = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
