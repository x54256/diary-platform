"""标签相关的请求/响应模型"""

from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, field_serializer

from schemas.common import serialize_utc_datetime


class TagCreate(BaseModel):
    """创建标签请求"""

    name: str
    type: Optional[str] = None


class TagResponse(BaseModel):
    """标签信息响应"""

    id: UUID
    user_id: UUID
    name: str
    type: Optional[str] = None
    created_at: datetime

    @field_serializer("created_at")
    def serialize_datetime(self, value: datetime):
        return serialize_utc_datetime(value)

    class Config:
        from_attributes = True
