"""标签相关的请求/响应模型"""

from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel


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

    class Config:
        from_attributes = True
