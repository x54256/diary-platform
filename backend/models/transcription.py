"""语音转写批次与音频项模型。"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import BigInteger, Column, Date, DateTime, ForeignKey, Index, Integer, String, Text, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from database import Base


class TranscriptionBatch(Base):
    __tablename__ = "transcription_batches"
    __table_args__ = (
        Index(
            "uq_transcription_active_user_date",
            "user_id",
            "diary_date",
            unique=True,
            postgresql_where=text("status IN ('QUEUED', 'PROCESSING', 'PARTIAL_FAILED', 'FINALIZING')"),
        ),
        Index("ix_transcription_batches_status_updated", "status", "updated_at"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    diary_date = Column(Date, nullable=True)
    base_text = Column(Text, nullable=True)
    status = Column(String(30), nullable=False, default="COLLECTING")
    diary_id = Column(UUID(as_uuid=True), ForeignKey("diaries.id"), nullable=True, unique=True)
    error_message = Column(Text, nullable=True)
    started_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)
    expires_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    items = relationship(
        "TranscriptionItem",
        back_populates="batch",
        cascade="all, delete-orphan",
        order_by="TranscriptionItem.sort_order",
    )
    diary = relationship("Diary")


class TranscriptionItem(Base):
    __tablename__ = "transcription_items"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    batch_id = Column(
        UUID(as_uuid=True),
        ForeignKey("transcription_batches.id", ondelete="CASCADE"),
        nullable=False,
    )
    sort_order = Column(Integer, nullable=False)
    original_filename = Column(String(255), nullable=False)
    content_type = Column(String(100), nullable=False)
    file_size = Column(BigInteger, nullable=False, default=0)
    storage_path = Column(Text, nullable=True)
    status = Column(String(30), nullable=False, default="UPLOADING")
    provider_task_id = Column(String(100), nullable=True, unique=True)
    access_token_hash = Column(String(64), nullable=True)
    access_expires_at = Column(DateTime, nullable=True)
    transcript_text = Column(Text, nullable=True)
    provider_request_id = Column(String(100), nullable=True)
    error_code = Column(String(100), nullable=True)
    error_message = Column(Text, nullable=True)
    retry_count = Column(Integer, nullable=False, default=0)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    batch = relationship("TranscriptionBatch", back_populates="items")
