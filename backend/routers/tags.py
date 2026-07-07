"""标签管理路由"""

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from database import get_db
from models.tag import Tag, TagPath
from models.user import User
from schemas.tag import TagCreate, TagResponse
from services.auth import get_current_user

router = APIRouter(prefix="/api/tags", tags=["标签管理"])


@router.get("", response_model=list[TagResponse])
def get_tags(
    tag_paths: str | None = Query(
        None,
        description="按标签路径前缀过滤，多路径用逗号分隔，如：'情绪/正面,认知/'"
    ),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """获取当前用户的所有标签，按创建时间倒序排列。

    支持通过 tag_paths 参数进行前缀过滤，返回路径匹配的所有标签。
    """
    query = db.query(Tag).filter(Tag.user_id == current_user.id)

    if tag_paths:
        # 解析逗号分隔的多路径
        paths = [p.strip() for p in tag_paths.split(",") if p.strip()]
        if paths:
            # 通过 tag_paths 表进行前缀匹配
            import sqlalchemy as sa
            conditions = [TagPath.path.like(f"{p}%") for p in paths]
            matching_tag_ids = (
                db.query(TagPath.tag_id)
                .filter(sa.or_(*conditions))
                .subquery()
            )
            query = query.filter(Tag.id.in_(matching_tag_ids))

    tags = query.order_by(Tag.created_at.desc()).all()
    return tags


@router.post("", response_model=TagResponse, status_code=status.HTTP_201_CREATED)
def create_tag(
    tag_data: TagCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """创建标签，同一用户下标签名不可重复"""
    tag = Tag(name=tag_data.name, type=tag_data.type, user_id=current_user.id)
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
