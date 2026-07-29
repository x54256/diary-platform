"""LLM 调用性能明细。"""

import uuid
from datetime import datetime

from sqlalchemy import Column, DateTime, Integer, String
from sqlalchemy.dialects.postgresql import UUID

from database import Base


class LlmCallLog(Base):
    """每次语言类 LLM 调用的性能和 token 统计。"""

    __tablename__ = "llm_call_logs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    step_name = Column(String(100), nullable=False)
    model_name = Column(String(200), nullable=True)
    prompt_tokens = Column(Integer, nullable=False)
    prompt_tokens_source = Column(String(20), nullable=False)  # usage / estimated
    duration_ms = Column(Integer, nullable=False)
    status = Column(String(20), nullable=False)  # success / failed
    error_type = Column(String(100), nullable=True)
    request_id = Column(String(100), nullable=True)
    chain_id = Column(String(100), nullable=True)
