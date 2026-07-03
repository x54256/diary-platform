"""用户相关的请求/响应模型"""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel


class UserCreate(BaseModel):
    """用户注册请求"""

    username: str
    password: str


class UserLogin(BaseModel):
    """用户登录请求"""

    username: str
    password: str


class UserResponse(BaseModel):
    """用户信息响应"""

    id: UUID
    username: str
    created_at: datetime

    class Config:
        from_attributes = True


class TokenResponse(BaseModel):
    """登录成功后返回的令牌信息"""

    access_token: str
    token_type: str = "bearer"
    user: UserResponse
