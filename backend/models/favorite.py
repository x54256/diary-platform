"""收藏数据模型。"""

import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, Column, DateTime, ForeignKey, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from database import Base


class Favorite(Base):
    """用户收藏的一篇日记或一个日记事件。"""

    __tablename__ = "favorites"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    diary_id = Column(UUID(as_uuid=True), ForeignKey("diaries.id", ondelete="CASCADE"), nullable=True)
    event_id = Column(UUID(as_uuid=True), ForeignKey("diary_events.id", ondelete="CASCADE"), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    user = relationship("User", back_populates="favorites")
    diary = relationship("Diary", back_populates="favorites")
    event = relationship("DiaryEvent", back_populates="favorites")

    __table_args__ = (
        CheckConstraint(
            "(diary_id IS NOT NULL AND event_id IS NULL) OR (diary_id IS NULL AND event_id IS NOT NULL)",
            name="ck_favorites_exactly_one_target",
        ),
        UniqueConstraint("user_id", "diary_id", name="uq_favorites_user_diary"),
        UniqueConstraint("user_id", "event_id", name="uq_favorites_user_event"),
    )
