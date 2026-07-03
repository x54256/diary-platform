"""认证路由"""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from database import get_db
from models.user import User
from schemas.user import UserLogin, UserResponse, TokenResponse
from services.auth import create_access_token, get_current_user
from utils.crypto import verify_password

router = APIRouter(prefix="/api/auth", tags=["认证"])


@router.post("/login", response_model=TokenResponse)
def login(credentials: UserLogin, db: Session = Depends(get_db)):
    """用户登录：验证用户名密码，返回 JWT 令牌

    Args:
        credentials: 登录凭据（用户名 + 密码）
        db: 数据库会话

    Returns:
        TokenResponse: 访问令牌和用户信息

    Raises:
        HTTPException: 用户名或密码错误时返回 401
    """
    # 查询用户
    user = db.query(User).filter(User.username == credentials.username).first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="用户名或密码错误",
        )

    # 验证密码
    if not verify_password(credentials.password, user.password_encrypted):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="用户名或密码错误",
        )

    # 生成 JWT 令牌
    token = create_access_token(data={"sub": user.username})
    return TokenResponse(
        access_token=token,
        token_type="bearer",
        user=UserResponse.model_validate(user),
    )


@router.post("/logout")
def logout():
    """用户登出

    JWT 是无状态令牌，服务端无需额外处理，前端丢弃令牌即可。
    """
    return {"message": "登出成功"}


@router.get("/me", response_model=UserResponse)
def get_me(current_user: User = Depends(get_current_user)):
    """获取当前登录用户信息

    需要在请求头中携带 Bearer 令牌：
        Authorization: Bearer <access_token>
    """
    return current_user
