"""对话管理路由"""

from datetime import datetime, timedelta
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from database import get_db
from models.dialog import Dialog, DialogMessage, MessageRole, SourceType
from models.diary import Diary
from models.user import User
from schemas.dialog import (
    DialogCreate,
    DialogResponse,
    MessageCreate,
    MessageResponse,
)
from services.ai import ai_service
from services.auth import get_current_user

router = APIRouter(prefix="/api/dialogs", tags=["对话管理"])


@router.post("", response_model=DialogResponse, status_code=status.HTTP_201_CREATED)
def create_dialog(
    dialog_data: DialogCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """创建对话"""
    try:
        source_type = SourceType(dialog_data.source_type)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"无效的来源类型: {dialog_data.source_type}",
        )

    dialog = Dialog(
        user_id=current_user.id,
        source_type=source_type,
        source_id=dialog_data.source_id,
    )
    db.add(dialog)
    db.commit()
    db.refresh(dialog)
    return dialog


@router.get("/{dialog_id}/messages", response_model=list[MessageResponse])
def get_messages(
    dialog_id: UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """获取对话的所有消息，按创建时间升序排列"""
    # 验证对话属于当前用户
    dialog = db.query(Dialog).filter(Dialog.id == dialog_id).first()
    if not dialog or dialog.user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="对话不存在",
        )

    messages = (
        db.query(DialogMessage)
        .filter(DialogMessage.dialog_id == dialog_id)
        .order_by(DialogMessage.created_at.asc())
        .all()
    )
    return messages


@router.post("/{dialog_id}/messages", response_model=MessageResponse)
async def send_message(
    dialog_id: UUID,
    message_data: MessageCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """发送消息并获取 AI 回复

    流程：
    1. 验证对话属于当前用户
    2. 保存用户消息
    3. 获取对话历史消息
    4. 根据 source_type 构建上下文
    5. 调用 AI 服务获取回复
    6. 保存 AI 回复并返回
    """
    # 验证对话属于当前用户
    dialog = db.query(Dialog).filter(Dialog.id == dialog_id).first()
    if not dialog or dialog.user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="对话不存在",
        )

    # a) 保存用户消息到 dialog_messages
    user_message = DialogMessage(
        dialog_id=dialog.id,
        role=MessageRole.user,
        content=message_data.content,
    )
    db.add(user_message)
    db.commit()
    db.refresh(user_message)

    # b) 获取对话历史消息（包括刚保存的）
    history_messages = (
        db.query(DialogMessage)
        .filter(DialogMessage.dialog_id == dialog.id)
        .order_by(DialogMessage.created_at.asc())
        .all()
    )

    # c) 根据 source_type 构建上下文
    context = ""
    if dialog.source_type == SourceType.diary_detail:
        # 获取 source_id 对应的日记内容作为上下文
        if dialog.source_id:
            diary = (
                db.query(Diary).filter(Diary.id == dialog.source_id).first()
            )
            if diary:
                context = f"日记原文：\n{diary.original_text}\n\n"
                if diary.organized:
                    org = diary.organized
                    context += f"整理标题：{org.title or ''}\n"
                    context += f"摘要：{org.summary or ''}\n"
                    context += f"整理内容：\n{org.content or ''}\n"
                    if org.mood:
                        context += f"心情：{org.mood}\n"
                    if org.location:
                        context += f"地点：{org.location}\n"
    elif dialog.source_type == SourceType.review:
        # 获取近期日记（最近 7 天）作为上下文
        seven_days_ago = (datetime.utcnow() - timedelta(days=7)).date()
        recent_diaries = (
            db.query(Diary)
            .filter(
                Diary.user_id == current_user.id,
                Diary.diary_date >= seven_days_ago,
            )
            .order_by(Diary.diary_date.asc())
            .all()
        )
        if recent_diaries:
            diary_texts = [
                f"[{d.diary_date}] {d.original_text}" for d in recent_diaries
            ]
            context = "近期日记：\n" + "\n\n".join(diary_texts)
    # ai_companion: context 保持为空字符串

    # d) 调用 AI 服务
    chat_messages = [
        {"role": msg.role.value, "content": msg.content}
        for msg in history_messages
    ]
    ai_reply = await ai_service.chat(chat_messages, context)

    # e) 保存 AI 回复到 dialog_messages
    assistant_message = DialogMessage(
        dialog_id=dialog.id,
        role=MessageRole.assistant,
        content=ai_reply,
    )
    db.add(assistant_message)
    db.commit()
    db.refresh(assistant_message)

    # f) 返回 AI 回复
    return assistant_message
