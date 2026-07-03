"""标签相关的请求/响应模型"""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel


class TagCreate(BaseModel):
    """创建标签请求"""

    name: str


class TagResponse(BaseModel):
    """标签信息响应"""

    id: UUID
    user_id: UUID
    name: str
    created_at: datetime

    class Config:
        from_attributes = True
