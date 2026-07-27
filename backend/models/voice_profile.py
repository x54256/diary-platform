"""用户热词与人物关系资料。"""

import uuid
from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, JSON, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from database import Base


class HotWord(Base):
    """当前用户维护的手工热词。"""

    __tablename__ = "hot_words"
    __table_args__ = (
        UniqueConstraint("user_id", "text", name="uq_hot_words_user_text"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    text = Column(String(100), nullable=False)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    user = relationship("User", back_populates="hot_words")


class PersonRelation(Base):
    """当前用户维护的人物关系资料。"""

    __tablename__ = "person_relations"
    __table_args__ = (
        UniqueConstraint("user_id", "name", name="uq_person_relations_user_name"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    name = Column(String(100), nullable=False)
    common_names = Column(JSON, nullable=False, default=list)
    gender = Column(String(20), nullable=False, default="unknown")
    relation = Column(String(100), nullable=False)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    user = relationship("User", back_populates="person_relations")


class AsrVocabulary(Base):
    """当前用户在阿里云 ASR 侧使用的热词列表状态。"""

    __tablename__ = "asr_vocabularies"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )
    vocabulary_id = Column(String(200), nullable=True)
    target_model = Column(String(200), nullable=True)
    fingerprint = Column(String(64), nullable=True)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    user = relationship("User", back_populates="asr_vocabulary")
