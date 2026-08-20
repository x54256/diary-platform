"""管理端搜索索引重建任务。"""

import uuid
from datetime import date, datetime

from sqlalchemy import Column, Date, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID

from database import Base
from services.task_environment import TASK_ENVIRONMENT


class SearchIndexRebuildJob(Base):
    """按日记日期范围重建关键词片段和语义向量的持久化任务。"""

    __tablename__ = "search_index_rebuild_jobs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    environment = Column(String(32), nullable=False, default=TASK_ENVIRONMENT)
    operator_user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    start_date = Column(Date, nullable=False)
    end_date = Column(Date, nullable=False)
    status = Column(String(20), nullable=False, default="queued")
    total_events = Column(Integer, nullable=False, default=0)
    processed_events = Column(Integer, nullable=False, default=0)
    succeeded_events = Column(Integer, nullable=False, default=0)
    failed_events = Column(Integer, nullable=False, default=0)
    last_event_id = Column(UUID(as_uuid=True), nullable=True)
    failure_details = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    started_at = Column(DateTime, nullable=True)
    finished_at = Column(DateTime, nullable=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
