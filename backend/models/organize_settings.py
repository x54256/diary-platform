"""日记整理流水线配置。"""

from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer
from sqlalchemy.dialects.postgresql import UUID

from database import Base


class OrganizePipelineSetting(Base):
    """整理流水线开关，固定只保留一条全局配置。"""

    __tablename__ = "organize_pipeline_settings"

    id = Column(Integer, primary_key=True, default=1)
    clean_check_enabled = Column(Boolean, nullable=False, default=False)
    content_check_enabled = Column(Boolean, nullable=False, default=False)
    updated_by = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
