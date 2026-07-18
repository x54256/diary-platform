"""用户相关的请求/响应模型"""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field, field_serializer

from schemas.common import serialize_utc_datetime


class UserCreate(BaseModel):
    """用户注册请求"""

    username: str = Field(min_length=1, max_length=50)
    password: str = Field(min_length=6)


class UserLogin(BaseModel):
    """用户登录请求"""

    username: str
    password: str


class UserResponse(BaseModel):
    """用户信息响应"""

    id: UUID
    username: str
    created_at: datetime

    @field_serializer("created_at")
    def serialize_datetime(self, value: datetime):
        return serialize_utc_datetime(value)

    class Config:
        from_attributes = True


class TokenResponse(BaseModel):
    """登录成功后返回的令牌信息"""

    access_token: str
    token_type: str = "bearer"
    user: UserResponse
