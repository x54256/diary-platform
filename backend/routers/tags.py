"""标签管理路由"""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from database import get_db
from models.tag import Tag
from models.user import User
from schemas.tag import TagCreate, TagResponse
from services.auth import get_current_user

router = APIRouter(prefix="/api/tags", tags=["标签管理"])


@router.get("", response_model=list[TagResponse])
def get_tags(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """获取当前用户的所有标签，按创建时间倒序排列"""
    tags = (
        db.query(Tag)
        .filter(Tag.user_id == current_user.id)
        .order_by(Tag.created_at.desc())
        .all()
    )
    return tags


@router.post("", response_model=TagResponse, status_code=status.HTTP_201_CREATED)
def create_tag(
    tag_data: TagCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """创建标签，同一用户下标签名不可重复"""
    tag = Tag(name=tag_data.name, user_id=current_user.id)
    db.add(tag)
    try:
        db.commit()
    except IntegrityError:
        # 同名标签已存在（UniqueConstraint 冲突）
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="同名标签已存在",
        )
    db.refresh(tag)
    return tag
