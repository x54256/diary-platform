"""日程任务与日程实例模型。"""

import uuid
from datetime import datetime

from sqlalchemy import Boolean, Column, Date, DateTime, ForeignKey, Index, Integer, String, Text, Time, UniqueConstraint
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
    execution_note = Column(Text, nullable=True)
    manually_modified = Column(Boolean, nullable=False, default=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    task = relationship("ScheduleTask", back_populates="occurrences")

    @property
    def recurrence_type(self):
        return self.task.recurrence_type if self.task else "NONE"

    @property
    def recurrence_until(self):
        return self.task.recurrence_until if self.task else None

    @property
    def recurrence_count(self):
        return int(self.task.recurrence_count) if self.task and self.task.recurrence_count else None

    @property
    def interval(self):
        return int(self.task.interval or 1) if self.task else 1

    @property
    def weekdays(self):
        if not self.task or not self.task.weekdays:
            return []
        return [int(value) for value in self.task.weekdays.split(",") if value != ""]

    @property
    def nth_week(self):
        return int(self.task.nth_week) if self.task and self.task.nth_week else None

    @property
    def nth_weekday(self):
        return int(self.task.nth_weekday) if self.task and self.task.nth_weekday else None


class ScheduleHolidayYear(Base):
    __tablename__ = "schedule_holiday_years"

    year = Column(Integer, primary_key=True)
    is_available = Column(Boolean, nullable=False, default=False)
    workdays = Column(Text, nullable=False, default="[]")
    restdays = Column(Text, nullable=False, default="[]")
    fetched_at = Column(DateTime, nullable=False, default=datetime.utcnow)


class ScheduleMaintenanceJob(Base):
    __tablename__ = "schedule_maintenance_jobs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    task_id = Column(UUID(as_uuid=True), ForeignKey("schedule_tasks.id", ondelete="CASCADE"), nullable=False)
    operation = Column(String(20), nullable=False)  # ENSURE / DELETE
    scheduled_from = Column(Date, nullable=False)
    status = Column(String(20), nullable=False, default="queued")  # queued / running / completed
    attempts = Column(Integer, nullable=False, default=0)
    available_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    last_error = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
