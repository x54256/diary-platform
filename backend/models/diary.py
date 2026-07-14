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

    draft = "draft"          # 草稿
    published = "published"  # 已发布
    organized = "organized"  # 已整理
    analyzed = "analyzed"    # 已分析


class Diary(Base):
    """日记表"""

    __tablename__ = "diaries"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    original_text = Column(Text, nullable=False)
    diary_date = Column(Date, nullable=False)
    status = Column(Enum(DiaryStatus), default=DiaryStatus.draft)
    is_dirty = Column(Boolean, default=False, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # 关系映射
    user = relationship("User", back_populates="diaries")
    # 1:1 关系，日记整理内容
    organized = relationship(
        "DiaryOrganized",
        back_populates="diary",
        uselist=False,
        cascade="all, delete-orphan",
    )
    # M:N 关系，日记标签
    tags = relationship("Tag", secondary="diary_tags", back_populates="diaries")


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
    # 分析结果（1:1）
    analysis = relationship(
        "DiaryAnalysis",
        back_populates="organized",
        uselist=False,
        cascade="all, delete-orphan",
    )


class DiaryAnalysis(Base):
    """日记分析结果表（与 diary_organized 表 1:1 关系）"""

    __tablename__ = "diary_analysis"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    task_id = Column(UUID(as_uuid=True), ForeignKey("organize_tasks.id"), nullable=False)
    diary_organized_id = Column(
        UUID(as_uuid=True), ForeignKey("diary_organized.id"), unique=True, nullable=False
    )
    mood = Column(String(50))                          # 当天整体心情
    emotion_analyses = Column(Text, nullable=True)     # 情绪分析
    behavior_decision_analyses = Column(Text, nullable=True)  # 行为与决策分析
    self_understanding_analyses = Column(Text, nullable=True)  # 自我理解
    action_suggestions = Column(Text, nullable=True)   # 行动建议
    cognitive_calibration_analyses = Column(Text, nullable=True)  # 认知校准
    cognitive_enhancements = Column(Text, nullable=True)  # 认知提升
    analyzed_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # 关系映射
    organized = relationship("DiaryOrganized", back_populates="analysis")


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
    analysis = Column(Text, nullable=True)  # JSON 序列化的事件级分析结果
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
    current_step = Column(String(50), nullable=True)  # text_cleaning / clean_checking / event_organizing / structuring / content_checking / metadata_extracting
    error_message = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
