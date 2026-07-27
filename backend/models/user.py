"""用户数据模型"""

import uuid
from datetime import datetime

from sqlalchemy import Column, String, DateTime
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from database import Base


class User(Base):
    """用户表"""

    __tablename__ = "users"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    username = Column(String(50), unique=True, nullable=False)
    password_encrypted = Column(String(500), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    # 关系映射
    diaries = relationship(
        "Diary",
        back_populates="user",
        cascade="all, delete-orphan",
        foreign_keys="Diary.user_id",
    )
    tags = relationship("Tag", back_populates="user", cascade="all, delete-orphan")
    dialogs = relationship("Dialog", back_populates="user", cascade="all, delete-orphan")
    schedule_tasks = relationship("ScheduleTask", back_populates="user", cascade="all, delete-orphan")
    hot_words = relationship("HotWord", back_populates="user", cascade="all, delete-orphan")
    person_relations = relationship("PersonRelation", back_populates="user", cascade="all, delete-orphan")
    asr_vocabulary = relationship("AsrVocabulary", back_populates="user", cascade="all, delete-orphan", uselist=False)
