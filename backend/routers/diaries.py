"""日记管理路由"""

import json
from datetime import date, timedelta
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import or_
from sqlalchemy.orm import Session

from database import get_db
from models.diary import Diary, DiaryOrganized, DiaryStatus, DiaryAnalysis
from models.tag import Tag
from models.user import User
from schemas.diary import (
    DiaryCalendarItem,
    DiaryCreate,
    DiaryOrganizedResponse,
    DiaryOrganizedUpdate,
    DiaryResponse,
    DiaryTagsUpdate,
)
from services.ai import ai_service
from services.auth import get_current_user

import asyncio
from database import SessionLocal
from utils.diary_render import render_diary_to_markdown
from models.diary import DiaryEvent, DiaryCheckLog, DiaryCleanCheckLog, OrganizeTask
from schemas.diary import OrganizeTaskResponse

router = APIRouter(prefix="/api/diaries", tags=["日记管理"])


# ─────────────────── 创建 / 列表 / 日历 / 搜索 ───────────────────
# 注意：静态路径（calendar、search）必须在 {diary_id} 之前注册，
# 否则会被 {diary_id} 匹配。


@router.post("", response_model=DiaryResponse, status_code=status.HTTP_201_CREATED)
def create_diary(
    diary_data: DiaryCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """创建日记（草稿）"""
    diary = Diary(
        user_id=current_user.id,
        original_text=diary_data.original_text,
        diary_date=diary_data.diary_date,
        status=DiaryStatus.draft,
    )
    db.add(diary)
    db.flush()  # 获取生成的 ID

    # 关联标签（仅关联属于当前用户的标签）
    if diary_data.tag_ids:
        tags = (
            db.query(Tag)
            .filter(Tag.id.in_(diary_data.tag_ids), Tag.user_id == current_user.id)
            .all()
        )
        diary.tags = tags

    db.commit()
    db.refresh(diary)
    return diary


@router.get("", response_model=list[DiaryResponse])
def list_diaries(
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    tag_id: Optional[UUID] = None,
    view_type: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """获取日记列表，支持按日期范围、标签筛选，按日期倒序排列"""
    query = db.query(Diary).filter(Diary.user_id == current_user.id)

    if start_date:
        query = query.filter(Diary.diary_date >= start_date)
    if end_date:
        query = query.filter(Diary.diary_date <= end_date)
    if tag_id:
        # 使用 any 子查询避免 join 产生重复记录
        query = query.filter(Diary.tags.any(Tag.id == tag_id))

    query = query.order_by(Diary.diary_date.desc())
    return query.all()


@router.get("/calendar", response_model=list[DiaryCalendarItem])
def get_calendar(
    year: int = Query(..., ge=1, le=9999),
    month: int = Query(..., ge=1, le=12),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """获取指定月份的日历视图数据，返回每天的日记概要"""
    # 计算月份的起止日期
    start = date(year, month, 1)
    if month == 12:
        end = date(year, 12, 31)
    else:
        end = date(year, month + 1, 1) - timedelta(days=1)

    diaries = (
        db.query(Diary)
        .filter(
            Diary.user_id == current_user.id,
            Diary.diary_date >= start,
            Diary.diary_date <= end,
        )
        .order_by(Diary.diary_date)
        .all()
    )

    result = []
    for diary in diaries:
        mood = diary.organized.mood if diary.organized else None
        # 将枚举状态转为字符串值
        status_value = diary.status.value if hasattr(diary.status, "value") else str(diary.status)
        result.append(
            DiaryCalendarItem(
                diary_date=diary.diary_date,
                mood=mood,
                status=status_value,
            )
        )
    return result


@router.get("/search", response_model=list[DiaryResponse])
def search_diaries(
    q: str = Query(..., min_length=1, description="搜索关键词"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """全文搜索已整理的日记（搜索 title、summary、content 字段）"""
    search_term = f"%{q}%"
    diaries = (
        db.query(Diary)
        .join(DiaryOrganized, Diary.id == DiaryOrganized.diary_id)
        .filter(
            Diary.user_id == current_user.id,
            Diary.status == DiaryStatus.organized,
            or_(
                DiaryOrganized.title.ilike(search_term),
                DiaryOrganized.summary.ilike(search_term),
                DiaryOrganized.content.ilike(search_term),
            ),
        )
        .order_by(Diary.diary_date.desc())
        .all()
    )
    return diaries


# ─────────────────── 日记详情 / 状态变更 / 整理 / 标签 ───────────────────


@router.get("/{diary_id}", response_model=DiaryResponse)
def get_diary(
    diary_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """获取日记详情（包含整理内容和标签）"""
    diary = (
        db.query(Diary)
        .filter(Diary.id == diary_id, Diary.user_id == current_user.id)
        .first()
    )
    if not diary:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="日记不存在")
    return diary


@router.put("/{diary_id}/publish", response_model=DiaryResponse)
def publish_diary(
    diary_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """发布日记：将状态从 draft 改为 published"""
    diary = (
        db.query(Diary)
        .filter(Diary.id == diary_id, Diary.user_id == current_user.id)
        .first()
    )
    if not diary:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="日记不存在")

    diary.status = DiaryStatus.published
    db.commit()
    db.refresh(diary)
    return diary


@router.post("/{diary_id}/organize", response_model=OrganizeTaskResponse)
async def organize_diary(
    diary_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """AI 整理日记：异步任务模式，立即返回任务状态"""
    # 1. 查找日记，校验属于当前用户
    diary = (
        db.query(Diary)
        .filter(Diary.id == diary_id, Diary.user_id == current_user.id)
        .first()
    )
    if not diary:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="日记不存在")

    # 2. 状态守卫：仅 published、organized 可重新整理；analyzed 不可
    if diary.status not in (DiaryStatus.published, DiaryStatus.organized):
        if diary.status == DiaryStatus.analyzed:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="已分析的日记不可重新整理，只能重新分析",
            )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="仅已发布或已整理的日记可以整理",
        )

    # 3. 检查是否已有 running 整理任务，有则返回当前任务状态
    existing_task = (
        db.query(OrganizeTask)
        .filter(
            OrganizeTask.diary_id == diary_id,
            OrganizeTask.user_id == current_user.id,
            OrganizeTask.task_type == "organize",
            OrganizeTask.status == "running",
        )
        .with_for_update()
        .first()
    )
    if existing_task:
        # 超时自动恢复：运行超过15分钟的任务视为失败
        from datetime import datetime, timedelta
        if datetime.utcnow() - existing_task.created_at > timedelta(minutes=15):
            existing_task.status = "failed"
            existing_task.error_message = "整理任务超时，已自动终止"
            db.commit()
        else:
            return OrganizeTaskResponse(
                diary_id=diary_id,
                status=existing_task.status,
                task_type="organize",
                current_step=existing_task.current_step,
                error_message=existing_task.error_message,
            )

    # 4. 检查是否存在 failed 整理任务（断点续跑：复用 task_id）
    failed_task = (
        db.query(OrganizeTask)
        .filter(
            OrganizeTask.diary_id == diary_id,
            OrganizeTask.user_id == current_user.id,
            OrganizeTask.task_type == "organize",
            OrganizeTask.status == "failed",
        )
        .order_by(OrganizeTask.created_at.desc())
        .first()
    )
    if failed_task:
        failed_task.status = "running"
        failed_task.error_message = None
        failed_task.current_step = "text_cleaning"
        db.commit()
        db.refresh(failed_task)
        task = failed_task
    else:
        # 5. 创建新 OrganizeTask 记录
        task = OrganizeTask(
            diary_id=diary_id,
            user_id=current_user.id,
            task_type="organize",
            status="running",
            current_step="text_cleaning",
        )
        db.add(task)
        db.commit()
        db.refresh(task)

    # 6. 启动后台异步任务
    asyncio.create_task(
        _run_organize(str(task.id), str(diary_id), diary.original_text, str(current_user.id))
    )

    # 7. 立即返回任务状态
    return OrganizeTaskResponse(
        diary_id=diary_id,
        status="running",
        task_type="organize",
        current_step="text_cleaning",
        error_message=None,
    )


async def _run_organize(task_id: str, diary_id: str, original_text: str, user_id: str):
    """后台执行 AI 整理（独立 DB session）"""
    db = SessionLocal()
    try:
        # 调用 AI 服务（LangGraph 流水线，进度由 Node 内部更新）
        result = await ai_service.organize_diary(
            original_text, task_id=task_id, diary_id=diary_id, user_id=user_id
        )

        # 生成 content markdown
        content = render_diary_to_markdown(
            events=result["events"],
            introduction=result.get("introduction", ""),
            trivia=result.get("trivia"),
            plans=result.get("plans"),
        )

        # 创建 DiaryOrganized 记录
        organized = DiaryOrganized(
            task_id=task_id,
            diary_id=diary_id,
            title=result["title"],
            summary=result["summary"],
            content=content,
            location=result["location"],
            introduction=result.get("introduction", ""),
            trivia=json.dumps(result.get("trivia", []), ensure_ascii=False),
            plans=json.dumps(result.get("plans", []), ensure_ascii=False),
        )
        db.add(organized)
        db.flush()

        # 创建 DiaryEvent 记录（event_tags 留空，由分析阶段产出）
        for i, event in enumerate(result["events"]):
            event_title = event.get("title", "未命名事件")
            db.add(DiaryEvent(
                diary_organized_id=organized.id,
                event_title=event_title,
                body=json.dumps(event.get("body", []), ensure_ascii=False),
                feeling=json.dumps(event.get("feeling", []), ensure_ascii=False),
                reflection=json.dumps(event.get("reflection", []), ensure_ascii=False),
                event_tags=json.dumps({}, ensure_ascii=False),
                sort_order=i,
            ))

        # 创建 DiaryCheckLog 记录
        for i, log in enumerate(result["check_log"]):
            db.add(DiaryCheckLog(
                diary_organized_id=organized.id,
                check_item=log.get("check_item", ""),
                status=log.get("status", "通过"),
                issue=log.get("issue", ""),
                before=log.get("before", ""),
                after=log.get("after", ""),
                target=log.get("target", ""),
                reason=log.get("reason", ""),
                sort_order=i,
            ))

        # 创建 DiaryCleanCheckLog 记录
        for i, log in enumerate(result.get("clean_check_log", [])):
            db.add(DiaryCleanCheckLog(
                diary_organized_id=organized.id,
                issue=log.get("issue", ""),
                before=log.get("before", ""),
                after=log.get("after", ""),
                reason=log.get("reason", ""),
                sort_order=i,
            ))

        # 更新日记状态
        diary = db.query(Diary).filter(Diary.id == diary_id).first()
        if diary:
            diary.status = DiaryStatus.organized

        # 更新任务状态
        task = db.query(OrganizeTask).filter(OrganizeTask.id == task_id).first()
        if task:
            task.status = "completed"
            task.current_step = None

        db.commit()

        # 清理 checkpoint 数据（流水线已成功完成，不再需要断点续跑）
        from services.pipeline import cleanup_checkpoint
        await cleanup_checkpoint(task_id)
    except Exception as e:
        # 任务失败：日记保持 published，记录错误
        import logging
        logging.getLogger(__name__).error("后台整理任务失败: %s", e)
        db.rollback()  # 必须先 rollback 恢复 session
        task = db.query(OrganizeTask).filter(OrganizeTask.id == task_id).first()
        if task:
            task.status = "failed"
            task.error_message = str(e)
        db.commit()
    finally:
        db.close()


@router.get("/{diary_id}/organize/status", response_model=OrganizeTaskResponse)
def get_organize_status(
    diary_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """查询整理任务状态"""
    task = (
        db.query(OrganizeTask)
        .filter(
            OrganizeTask.diary_id == diary_id,
            OrganizeTask.user_id == current_user.id,
            OrganizeTask.task_type == "organize",
        )
        .order_by(OrganizeTask.created_at.desc())
        .first()
    )
    if not task:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="无整理任务")
    return OrganizeTaskResponse(
        diary_id=diary_id,
        status=task.status,
        task_type=task.task_type,
        current_step=task.current_step,
        error_message=task.error_message,
    )


@router.post("/{diary_id}/analyze", response_model=OrganizeTaskResponse)
async def analyze_diary(
    diary_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """AI 分析日记：异步任务模式，立即返回任务状态"""
    # 1. 查找日记，校验属于当前用户
    diary = (
        db.query(Diary)
        .filter(Diary.id == diary_id, Diary.user_id == current_user.id)
        .first()
    )
    if not diary:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="日记不存在")

    # 2. 状态守卫：仅 organized、analyzed 可触发分析
    if diary.status not in (DiaryStatus.organized, DiaryStatus.analyzed):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="仅已整理或已分析的日记可以触发分析",
        )

    # 3. 必须有整理记录才能分析
    if not diary.organized:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="日记尚未整理，无法分析",
        )

    # 4. 检查是否已有 running 分析任务
    existing_task = (
        db.query(OrganizeTask)
        .filter(
            OrganizeTask.diary_id == diary_id,
            OrganizeTask.user_id == current_user.id,
            OrganizeTask.task_type == "analyze",
            OrganizeTask.status == "running",
        )
        .with_for_update()
        .first()
    )
    if existing_task:
        from datetime import datetime, timedelta
        if datetime.utcnow() - existing_task.created_at > timedelta(minutes=15):
            existing_task.status = "failed"
            existing_task.error_message = "分析任务超时，已自动终止"
            db.commit()
        else:
            return OrganizeTaskResponse(
                diary_id=diary_id,
                status=existing_task.status,
                task_type="analyze",
                current_step=existing_task.current_step,
                error_message=existing_task.error_message,
            )

    # 5. 检查是否存在 failed 分析任务（断点续跑：复用 task_id）
    failed_task = (
        db.query(OrganizeTask)
        .filter(
            OrganizeTask.diary_id == diary_id,
            OrganizeTask.user_id == current_user.id,
            OrganizeTask.task_type == "analyze",
            OrganizeTask.status == "failed",
        )
        .order_by(OrganizeTask.created_at.desc())
        .first()
    )
    if failed_task:
        failed_task.status = "running"
        failed_task.error_message = None
        failed_task.current_step = "mood_tag_extracting"
        db.commit()
        db.refresh(failed_task)
        task = failed_task
    else:
        # 6. 创建新 OrganizeTask 记录（task_type=analyze）
        task = OrganizeTask(
            diary_id=diary_id,
            user_id=current_user.id,
            task_type="analyze",
            status="running",
            current_step="mood_tag_extracting",
        )
        db.add(task)
        db.commit()
        db.refresh(task)

    # 7. 组装 structured_diary，供分析流水线使用
    diary_organized = diary.organized
    structured_diary = {
        "introduction": diary_organized.introduction or "",
        "events": [
            {
                "title": event.event_title,
                "body": json.loads(event.body) if isinstance(event.body, str) else event.body,
                "feeling": json.loads(event.feeling) if isinstance(event.feeling, str) else (event.feeling or []),
                "reflection": json.loads(event.reflection) if isinstance(event.reflection, str) else (event.reflection or []),
            }
            for event in diary_organized.events
        ],
        "trivia": json.loads(diary_organized.trivia) if isinstance(diary_organized.trivia, str) else (diary_organized.trivia or []),
        "plans": json.loads(diary_organized.plans) if isinstance(diary_organized.plans, str) else (diary_organized.plans or []),
    }

    # 8. 启动后台异步分析任务
    asyncio.create_task(
        _run_analyze(
            task_id=str(task.id),
            diary_id=str(diary_id),
            user_id=str(current_user.id),
            diary_organized_id=str(diary_organized.id),
            original_text=diary.original_text,
            structured_diary=structured_diary,
        )
    )

    # 9. 立即返回任务状态
    return OrganizeTaskResponse(
        diary_id=diary_id,
        status="running",
        task_type="analyze",
        current_step="mood_tag_extracting",
        error_message=None,
    )


async def _run_analyze(
    task_id: str,
    diary_id: str,
    user_id: str,
    diary_organized_id: str,
    original_text: str,
    structured_diary: dict,
):
    """后台执行 AI 分析（独立 DB session）"""
    db = SessionLocal()
    try:
        # 调用分析流水线（内部完成标签落库 + 结果存储 + 状态更新为 analyzed）
        await ai_service.analyze_diary(
            original_text=original_text,
            structured_diary=structured_diary,
            task_id=task_id,
            diary_id=diary_id,
            user_id=user_id,
            diary_organized_id=diary_organized_id,
        )

        # 更新任务状态
        task = db.query(OrganizeTask).filter(OrganizeTask.id == task_id).first()
        if task:
            task.status = "completed"
            task.current_step = None
        db.commit()
    except Exception as e:
        import logging
        logging.getLogger(__name__).error("后台分析任务失败: %s", e)
        db.rollback()
        task = db.query(OrganizeTask).filter(OrganizeTask.id == task_id).first()
        if task:
            task.status = "failed"
            task.error_message = str(e)
        db.commit()
    finally:
        db.close()


@router.get("/{diary_id}/analyze/status", response_model=OrganizeTaskResponse)
def get_analyze_status(
    diary_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """查询分析任务状态"""
    task = (
        db.query(OrganizeTask)
        .filter(
            OrganizeTask.diary_id == diary_id,
            OrganizeTask.user_id == current_user.id,
            OrganizeTask.task_type == "analyze",
        )
        .order_by(OrganizeTask.created_at.desc())
        .first()
    )
    if not task:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="无分析任务")
    return OrganizeTaskResponse(
        diary_id=diary_id,
        status=task.status,
        task_type=task.task_type,
        current_step=task.current_step,
        error_message=task.error_message,
    )


@router.put("/{diary_id}/organized", response_model=DiaryOrganizedResponse)
def update_organized(
    diary_id: UUID,
    update_data: DiaryOrganizedUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """修改日记的整理内容（仅更新非 None 的字段）"""
    diary = (
        db.query(Diary)
        .filter(Diary.id == diary_id, Diary.user_id == current_user.id)
        .first()
    )
    if not diary:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="日记不存在")
    if not diary.organized:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="日记尚未整理，无法修改整理内容",
        )
    # 状态守卫：仅 organized、analyzed 可修改结构化结果
    if diary.status not in (DiaryStatus.organized, DiaryStatus.analyzed):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="仅已整理或已分析的日记可以修改整理内容",
        )

    organized = diary.organized
    # 仅更新提供的字段（非 None）
    if update_data.title is not None:
        organized.title = update_data.title
    if update_data.summary is not None:
        organized.summary = update_data.summary
    if update_data.content is not None:
        organized.content = update_data.content
    if update_data.mood is not None:
        organized.mood = update_data.mood
    if update_data.location is not None:
        organized.location = update_data.location
    if update_data.introduction is not None:
        organized.introduction = update_data.introduction
    if update_data.trivia is not None:
        organized.trivia = json.dumps(update_data.trivia, ensure_ascii=False)
    if update_data.plans is not None:
        organized.plans = json.dumps(update_data.plans, ensure_ascii=False)

    db.commit()
    db.refresh(organized)
    return organized


@router.put("/{diary_id}/tags", response_model=DiaryResponse)
def update_diary_tags(
    diary_id: UUID,
    tags_data: DiaryTagsUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """更新日记标签：先删除现有关联，再建立新关联"""
    diary = (
        db.query(Diary)
        .filter(Diary.id == diary_id, Diary.user_id == current_user.id)
        .first()
    )
    if not diary:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="日记不存在")

    # 清空现有关联
    diary.tags = []
    db.flush()

    # 建立新关联（仅关联属于当前用户的标签）
    if tags_data.tag_ids:
        tags = (
            db.query(Tag)
            .filter(Tag.id.in_(tags_data.tag_ids), Tag.user_id == current_user.id)
            .all()
        )
        diary.tags = tags

    db.commit()
    db.refresh(diary)
    return diary
