"""日程任务与日程实例模型。"""

import uuid
from datetime import datetime

from sqlalchemy import Boolean, Column, Date, DateTime, ForeignKey, Index, String, Text, Time, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from database import Base


class ScheduleTask(Base):
    __tablename__ = "schedule_tasks"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    source_task_id = Column(UUID(as_uuid=True), ForeignKey("schedule_tasks.id"), nullable=True)
    title = Column(String(200), nullable=False)
    is_all_day = Column(Boolean, nullable=False, default=False)
    start_date = Column(Date, nullable=False)
    start_time = Column(Time, nullable=True)
    end_time = Column(Time, nullable=True)
    # NONE / DAILY / WEEKLY / MONTHLY_DATE / MONTHLY_NTH_WEEKDAY
    recurrence_type = Column(String(32), nullable=False, default="NONE")
    interval = Column(String(10), nullable=False, default="1")
    weekdays = Column(String(32), nullable=True)  # 0=周日，逗号分隔
    month_day = Column(String(2), nullable=True)
    nth_week = Column(String(1), nullable=True)
    nth_weekday = Column(String(1), nullable=True)
    recurrence_until = Column(Date, nullable=True)
    recurrence_count = Column(String(10), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    user = relationship("User", back_populates="schedule_tasks", foreign_keys=[user_id])
    occurrences = relationship("ScheduleOccurrence", back_populates="task", cascade="all, delete-orphan")


class ScheduleOccurrence(Base):
    __tablename__ = "schedule_occurrences"
    __table_args__ = (
        UniqueConstraint("task_id", "scheduled_date", name="uq_schedule_occurrence_date"),
        Index("ix_schedule_occurrences_user_date_status", "user_id", "scheduled_date", "status"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    task_id = Column(UUID(as_uuid=True), ForeignKey("schedule_tasks.id", ondelete="CASCADE"), nullable=False)
    scheduled_date = Column(Date, nullable=False)
    title = Column(String(200), nullable=False)
    is_all_day = Column(Boolean, nullable=False, default=False)
    start_time = Column(Time, nullable=True)
    end_time = Column(Time, nullable=True)
    status = Column(String(20), nullable=False, default="pending")
    completed_at = Column(DateTime, nullable=True)
    overdue_reason = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    task = relationship("ScheduleTask", back_populates="occurrences")

    @property
    def recurrence_type(self):
        return self.task.recurrence_type if self.task else "NONE"
