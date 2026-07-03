"""日记数据模型"""

import enum
import uuid
from datetime import datetime

from sqlalchemy import Column, String, Text, Date, DateTime, Enum, ForeignKey, Integer
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from database import Base


class DiaryStatus(enum.Enum):
    """日记状态枚举"""

    draft = "draft"          # 草稿
    published = "published"  # 已发布
    organized = "organized"  # 已整理


class Diary(Base):
    """日记表"""

    __tablename__ = "diaries"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    original_text = Column(Text, nullable=False)
    diary_date = Column(Date, nullable=False)
    status = Column(Enum(DiaryStatus), default=DiaryStatus.draft)
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
    diary_id = Column(
        UUID(as_uuid=True), ForeignKey("diaries.id"), unique=True, nullable=False
    )
    title = Column(String(200))
    summary = Column(Text)
    content = Column(Text)
    mood = Column(String(50))
    location = Column(String(100))
    organized_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # 关系映射
    diary = relationship("Diary", back_populates="organized")
    # 结构化事件（1:N）
    events = relationship("DiaryEvent", back_populates="organized", cascade="all, delete-orphan", order_by="DiaryEvent.sort_order")
    # 内容检查记录（1:N）
    check_logs = relationship("DiaryCheckLog", back_populates="organized", cascade="all, delete-orphan", order_by="DiaryCheckLog.sort_order")


class DiaryEvent(Base):
    """日记事件表（结构化日记的每个事件）"""

    __tablename__ = "diary_events"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    diary_organized_id = Column(UUID(as_uuid=True), ForeignKey("diary_organized.id"), nullable=False)
    event_title = Column(String(200))
    background = Column(Text)
    motivation = Column(Text)
    process = Column(Text)
    result = Column(Text)
    feeling = Column(Text)
    reflection = Column(Text)
    sort_order = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.utcnow)

    # 关系映射
    organized = relationship("DiaryOrganized", back_populates="events")


class DiaryCheckLog(Base):
    """内容检查记录表（内部保留，用户不可见）"""

    __tablename__ = "diary_check_logs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    diary_organized_id = Column(UUID(as_uuid=True), ForeignKey("diary_organized.id"), nullable=False)
    check_item = Column(String(100))
    status = Column(String(20))  # "通过" 或 "已修正"
    issue = Column(Text)
    fix = Column(Text)
    before = Column(Text)
    after = Column(Text)
    sort_order = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.utcnow)

    # 关系映射
    organized = relationship("DiaryOrganized", back_populates="check_logs")


class OrganizeTask(Base):
    """异步整理任务表"""

    __tablename__ = "organize_tasks"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    diary_id = Column(UUID(as_uuid=True), ForeignKey("diaries.id"), nullable=False)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    status = Column(String(20), default="running")  # running / completed / failed
    current_step = Column(String(50), nullable=True)  # text_cleaning / event_organizing / template_filling / content_checking / metadata_generating
    error_message = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
