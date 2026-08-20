"""系统备份与恢复模型"""

import uuid
from datetime import datetime

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID

from database import Base
from services.task_environment import TASK_ENVIRONMENT


class BackupRestoreRecord(Base):
    """备份恢复记录表"""

    __tablename__ = "backup_restore_records"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    environment = Column(String(32), nullable=False, default=TASK_ENVIRONMENT)
    operation_type = Column(String(30), nullable=False)
    status = Column(String(30), nullable=False, default="pending")
    scope_type = Column(String(30), nullable=True)
    scope_summary = Column(Text, nullable=True)
    current_phase = Column(String(100), nullable=True)
    current_table = Column(String(100), nullable=True)
    operator_user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    backup_package_id = Column(String(100), nullable=True)
    file_name = Column(String(255), nullable=True)
    file_path = Column(Text, nullable=True)
    file_expires_at = Column(DateTime, nullable=True)
    started_at = Column(DateTime, nullable=True)
    finished_at = Column(DateTime, nullable=True)
    result_summary = Column(Text, nullable=True)
    error_summary = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class BackupImportReport(Base):
    """备份导入报告表"""

    __tablename__ = "backup_import_reports"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    record_id = Column(UUID(as_uuid=True), ForeignKey("backup_restore_records.id"), nullable=False)
    table_name = Column(String(100), nullable=False)
    created_count = Column(Integer, default=0, nullable=False)
    skipped_count = Column(Integer, default=0, nullable=False)
    failed_count = Column(Integer, default=0, nullable=False)
    failure_summary = Column(Text, nullable=True)
    skip_summary = Column(Text, nullable=True)
    expires_at = Column(DateTime, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
