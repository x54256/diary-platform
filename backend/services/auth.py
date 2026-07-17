"""认证服务：JWT 令牌生成与验证"""

from datetime import datetime, timedelta
from typing import Optional

from fastapi import Depends, HTTPException, Response, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from sqlalchemy.orm import Session

from config import settings
from database import get_db
from models.user import User

# OAuth2 密码流，tokenUrl 指向登录接口
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login")


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    """创建 JWT 访问令牌

    Args:
        data: 要编码到令牌中的数据（如 {"sub": username}）
        expires_delta: 过期时间增量，默认 30 天

    Returns:
        JWT 令牌字符串
    """
    to_encode = data.copy()
    expire = datetime.utcnow() + (expires_delta or timedelta(days=30))
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, settings.SECRET_KEY, algorithm="HS256")


def get_current_user(
    response: Response,
    token: str = Depends(oauth2_scheme),
    db: Session = Depends(get_db),
) -> User:
    """从 JWT 令牌解析当前用户（FastAPI 依赖注入）

    Args:
        response: 用于返回续期令牌的 HTTP 响应
        token: Bearer 令牌
        db: 数据库会话

    Returns:
        当前登录的 User 对象

    Raises:
        HTTPException: 令牌无效或用户不存在时抛出 401
    """
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="无法验证凭据",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=["HS256"])
        username: Optional[str] = payload.get("sub")
        if username is None:
            raise credentials_exception
    except JWTError:
        raise credentials_exception

    user = db.query(User).filter(User.username == username).first()
    if user is None:
        raise credentials_exception

    # 每次成功的鉴权请求都将有效期向后延长 30 天。
    response.headers["X-Access-Token"] = create_access_token({"sub": username})
    return user
