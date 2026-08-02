"""对话数据模型"""

import enum
import uuid
from datetime import datetime

from sqlalchemy import Column, Text, DateTime, Enum, ForeignKey, Index, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from database import Base


class SourceType(enum.Enum):
    """对话来源类型枚举"""

    diary_detail = "diary_detail"    # 日记详情对话
    review = "review"                # 复盘对话
    ai_companion = "ai_companion"    # AI 伙伴对话


class MessageRole(enum.Enum):
    """消息角色枚举"""

    user = "user"                # 用户消息
    assistant = "assistant"      # AI 回复


class Dialog(Base):
    """对话表"""

    __tablename__ = "dialogs"
    __table_args__ = (
        Index(
            "uq_dialogs_user_review_source",
            "user_id", "source_type", "source_id",
            unique=True,
            postgresql_where=text("source_type = 'review' AND source_id IS NOT NULL"),
        ),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    source_type = Column(Enum(SourceType), nullable=False)
    source_id = Column(UUID(as_uuid=True), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # 关系映射
    user = relationship("User", back_populates="dialogs")
    messages = relationship(
        "DialogMessage", back_populates="dialog", cascade="all, delete-orphan"
    )


class DialogMessage(Base):
    """对话消息表"""

    __tablename__ = "dialog_messages"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    dialog_id = Column(UUID(as_uuid=True), ForeignKey("dialogs.id"), nullable=False)
    role = Column(Enum(MessageRole), nullable=False)
    content = Column(Text, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    # 关系映射
    dialog = relationship("Dialog", back_populates="messages")
