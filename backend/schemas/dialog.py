"""对话相关的请求/响应模型"""

from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel


class DialogCreate(BaseModel):
    """创建对话请求"""

    source_type: str
    source_id: Optional[UUID] = None


class MessageCreate(BaseModel):
    """发送消息请求"""

    content: str


class MessageResponse(BaseModel):
    """对话消息响应"""

    id: UUID
    dialog_id: UUID
    role: str
    content: str
    created_at: datetime

    class Config:
        from_attributes = True


class DialogResponse(BaseModel):
    """对话信息响应（含消息列表）"""

    id: UUID
    user_id: UUID
    source_type: str
    source_id: Optional[UUID] = None
    created_at: datetime
    updated_at: datetime
    messages: list[MessageResponse] = []

    class Config:
        from_attributes = True
