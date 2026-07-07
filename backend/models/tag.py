"""标签数据模型"""

import uuid
from datetime import datetime

from sqlalchemy import Column, String, DateTime, ForeignKey, UniqueConstraint, Table
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from database import Base


# 日记-标签 多对多关联表
diary_tags = Table(
    "diary_tags",
    Base.metadata,
    Column("diary_id", UUID(as_uuid=True), ForeignKey("diaries.id"), primary_key=True),
    Column("tag_id", UUID(as_uuid=True), ForeignKey("tags.id"), primary_key=True),
)


class EventTag(Base):
    """事件-标签关联表（M:N）"""

    __tablename__ = "event_tags"

    diary_event_id = Column(UUID(as_uuid=True), ForeignKey("diary_events.id"), primary_key=True)
    tag_id = Column(UUID(as_uuid=True), ForeignKey("tags.id"), primary_key=True)


class TagPath(Base):
    """标签路径表（用于前缀匹配）"""

    __tablename__ = "tag_paths"

    tag_id = Column(UUID(as_uuid=True), ForeignKey("tags.id"), primary_key=True)
    path = Column(String(500), nullable=False)


class Tag(Base):
    """标签表"""

    __tablename__ = "tags"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    name = Column(String(50), nullable=False)
    type = Column(String(30), nullable=True)  # 标签类型：domain/topic/person_object/psychological/knowledge
    created_at = Column(DateTime, default=datetime.utcnow)

    # 联合唯一约束：同一用户下标签名不重复
    __table_args__ = (
        UniqueConstraint("user_id", "name", name="uq_user_tag_name"),
    )

    # 关系映射
    user = relationship("User", back_populates="tags")
    # M:N 关系，关联的日记
    diaries = relationship("Diary", secondary="diary_tags", back_populates="tags")
    # M:N 关系，关联的事件
    events = relationship("DiaryEvent", secondary="event_tags", back_populates="tags")
