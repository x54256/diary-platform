"""日记管理路由"""

import json
import logging
from datetime import date, datetime, timedelta
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import or_
from sqlalchemy.orm import Session

from database import get_db
from models.diary import AnalysisFeedback, AnalysisRun, Diary, DiaryOrganized, DiaryStatus
from models.tag import EventTag, Tag, diary_tags
from models.user import User
from schemas.diary import (
    DiaryCalendarItem,
    DiaryCreate,
    DiaryOrganizedResponse,
    DiaryOrganizedUpdate,
    DiaryResponse,
    DiaryTagsUpdate,
    DiaryUpdate,
    AnalysisFeedbackResponse,
    AnalysisFeedbackUpsert,
)
from services.ai import ai_service
from services.analysis_history import (
    ALL_ANALYSIS_TYPES,
    build_run_response,
    build_sections,
    effective_feedback,
    get_current_analysis_run,
)
from services.auth import get_current_user

import asyncio
from database import SessionLocal
from utils.diary_render import render_diary_to_markdown
from models.diary import DiaryEvent, DiaryCheckLog, DiaryCleanCheckLog, OrganizeTask
from schemas.diary import OrganizeTaskResponse, DiaryEventUpdate, DiaryEventResponse

router = APIRouter(prefix="/api/diaries", tags=["日记管理"])


def parse_json_value(value, default):
    if value is None:
        return default
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            return parsed
        except (json.JSONDecodeError, TypeError):
            return default
    return value


def serialize_event(event: DiaryEvent, current_run: AnalysisRun | None, user_id: UUID) -> dict:
    return {
        "id": event.id,
        "event_title": event.event_title,
        "body": parse_json_value(event.body, []),
        "feeling": parse_json_value(event.feeling, []),
        "reflection": parse_json_value(event.reflection, []),
        "event_tags": parse_json_value(event.event_tags, None),
        "analysis": build_sections(current_run, user_id, "EVENT", event.id),
        "sort_order": event.sort_order,
        "tags": event.tags,
    }


def serialize_organized(organized: DiaryOrganized | None, current_run: AnalysisRun | None, user_id: UUID) -> dict | None:
    if not organized:
        return None
    return {
        "id": organized.id,
        "title": organized.title,
        "summary": organized.summary,
        "content": organized.content,
        "mood": organized.mood,
        "location": organized.location,
        "introduction": organized.introduction,
        "trivia": parse_json_value(organized.trivia, []),
        "plans": parse_json_value(organized.plans, []),
        "events": [
            serialize_event(event, current_run, user_id)
            for event in sorted(organized.events, key=lambda item: item.sort_order)
        ],
        "check_logs": organized.check_logs,
        "clean_check_logs": organized.clean_check_logs,
        "analysis": build_run_response(current_run, user_id),
    }


def serialize_diary(diary: Diary, db: Session, user_id: UUID) -> dict:
    current_run = get_current_analysis_run(db, diary.id)
    status_value = diary.status.value if hasattr(diary.status, "value") else str(diary.status)
    return {
        "id": diary.id,
        "user_id": diary.user_id,
        "original_text": diary.original_text,
        "diary_date": diary.diary_date,
        "status": status_value,
        "is_dirty": diary.is_dirty,
        "deleted_at": diary.deleted_at,
        "deleted_by": diary.deleted_by,
        "created_at": diary.created_at,
        "updated_at": diary.updated_at,
        "organized": serialize_organized(diary.organized, current_run, user_id),
        "tags": diary.tags,
    }


def active_diary_query(db: Session, current_user: User):
    return db.query(Diary).filter(
        Diary.user_id == current_user.id,
        Diary.deleted_at.is_(None),
    )


# ─────────────────── 创建 / 列表 / 日历 / 搜索 ───────────────────
# 注意：静态路径（calendar、search）必须在 {diary_id} 之前注册，
# 否则会被 {diary_id} 匹配。


@router.post("", response_model=DiaryResponse, status_code=status.HTTP_201_CREATED)
def create_diary(
    diary_data: DiaryCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """创建日记"""
    diary = Diary(
        user_id=current_user.id,
        original_text=diary_data.original_text,
        diary_date=diary_data.diary_date,
        status=DiaryStatus.saved,
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
    query = active_diary_query(db, current_user)

    if start_date:
        query = query.filter(Diary.diary_date >= start_date)
    if end_date:
        query = query.filter(Diary.diary_date <= end_date)
    if tag_id:
        # 使用 any 子查询避免 join 产生重复记录
        query = query.filter(Diary.tags.any(Tag.id == tag_id))

    query = query.order_by(Diary.diary_date.desc(), Diary.created_at.desc())
    return [serialize_diary(diary, db, current_user.id) for diary in query.all()]


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
            Diary.deleted_at.is_(None),
            Diary.diary_date >= start,
            Diary.diary_date <= end,
        )
        .order_by(Diary.diary_date)
        .all()
    )

    result = []
    for diary in diaries:
        current_run = get_current_analysis_run(db, diary.id)
        mood = current_run.mood if current_run and current_run.mood else (diary.organized.mood if diary.organized else None)
        # 将枚举状态转为字符串值
        status_value = diary.status.value if hasattr(diary.status, "value") else str(diary.status)
        result.append(
            DiaryCalendarItem(
                diary_date=diary.diary_date,
                mood=mood,
                status=status_value,
                is_dirty=diary.is_dirty,
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
            Diary.deleted_at.is_(None),
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
    return [serialize_diary(diary, db, current_user.id) for diary in diaries]


@router.put("/analysis-feedback", response_model=AnalysisFeedbackResponse)
def upsert_analysis_feedback(
    feedback_data: AnalysisFeedbackUpsert,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """保存或更新一个分析类型块反馈"""
    if feedback_data.rating < 1 or feedback_data.rating > 5:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="评分必须在 1-5 之间")
    if feedback_data.scope not in {"DIARY", "EVENT"}:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="反馈层级无效")
    if feedback_data.analysis_type not in ALL_ANALYSIS_TYPES:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="分析类型无效")
    if feedback_data.scope == "DIARY" and feedback_data.event_id is not None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="日记级反馈不能包含事件 ID")
    if feedback_data.scope == "EVENT" and feedback_data.event_id is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="事件级反馈必须包含事件 ID")

    run = (
        db.query(AnalysisRun)
        .join(Diary, Diary.id == AnalysisRun.diary_id)
        .filter(
            AnalysisRun.id == feedback_data.analysis_run_id,
            Diary.user_id == current_user.id,
            Diary.deleted_at.is_(None),
        )
        .first()
    )
    if not run:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="分析结果不存在")
    if run.status != "CURRENT":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="只能反馈当前分析结果")

    if feedback_data.scope == "EVENT":
        event = (
            db.query(DiaryEvent)
            .filter(
                DiaryEvent.id == feedback_data.event_id,
                DiaryEvent.diary_organized_id == run.diary_organized_id,
            )
            .first()
        )
        if not event:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="事件不存在")

    query = db.query(AnalysisFeedback).filter(
        AnalysisFeedback.analysis_run_id == feedback_data.analysis_run_id,
        AnalysisFeedback.user_id == current_user.id,
        AnalysisFeedback.scope == feedback_data.scope,
        AnalysisFeedback.analysis_type == feedback_data.analysis_type,
    )
    if feedback_data.event_id is None:
        query = query.filter(AnalysisFeedback.event_id.is_(None))
    else:
        query = query.filter(AnalysisFeedback.event_id == feedback_data.event_id)
    feedback = query.first()

    if feedback:
        feedback.rating = feedback_data.rating
        feedback.comment = feedback_data.comment
        feedback.is_inherited = False
        feedback.updated_at = datetime.utcnow()
    else:
        feedback = AnalysisFeedback(
            analysis_run_id=feedback_data.analysis_run_id,
            user_id=current_user.id,
            scope=feedback_data.scope,
            event_id=feedback_data.event_id,
            analysis_type=feedback_data.analysis_type,
            rating=feedback_data.rating,
            comment=feedback_data.comment,
            is_inherited=False,
        )
        db.add(feedback)

    db.commit()
    db.refresh(feedback)
    return feedback


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
        .filter(Diary.id == diary_id, Diary.user_id == current_user.id, Diary.deleted_at.is_(None))
        .first()
    )
    if not diary:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="日记不存在")
    return serialize_diary(diary, db, current_user.id)


@router.put("/{diary_id}", response_model=DiaryResponse)
def update_diary(
    diary_id: UUID,
    update_data: DiaryUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """更新日记原文（仅 saved 和 organized 状态可编辑）"""
    diary = (
        db.query(Diary)
        .filter(Diary.id == diary_id, Diary.user_id == current_user.id, Diary.deleted_at.is_(None))
        .first()
    )
    if not diary:
        raise HTTPException(status_code=404, detail="日记不存在")

    # 状态守卫：仅 saved、organized 可编辑原文
    if diary.status not in (DiaryStatus.saved, DiaryStatus.organized):
        raise HTTPException(
            status_code=400,
            detail="当前状态不允许编辑原文",
        )

    # 仅更新非 None 字段
    if update_data.original_text is not None:
        diary.original_text = update_data.original_text
    if update_data.diary_date is not None:
        diary.diary_date = update_data.diary_date

    # 脏标记：前端传 is_dirty=True 时置位（仅已整理/已分析状态有意义）
    if update_data.is_dirty is True:
        diary.is_dirty = True

    db.commit()
    db.refresh(diary)
    return serialize_diary(diary, db, current_user.id)


@router.delete("/{diary_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_diary(
    diary_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """软删除日记，保留整理、分析、反馈和任务数据"""
    diary = (
        db.query(Diary)
        .filter(Diary.id == diary_id, Diary.user_id == current_user.id, Diary.deleted_at.is_(None))
        .first()
    )
    if not diary:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="日记不存在")

    running_task = (
        db.query(OrganizeTask)
        .filter(
            OrganizeTask.diary_id == diary_id,
            OrganizeTask.user_id == current_user.id,
            OrganizeTask.status == "running",
        )
        .first()
    )
    if running_task:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="当前日记正在整理或分析，完成后再删除",
        )

    diary.deleted_at = datetime.utcnow()
    diary.deleted_by = current_user.id
    db.commit()


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
        .filter(Diary.id == diary_id, Diary.user_id == current_user.id, Diary.deleted_at.is_(None))
        .first()
    )
    if not diary:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="日记不存在")

    # 2. 状态守卫：仅 saved、organized 可整理；analyzed 不可
    if diary.status not in (DiaryStatus.saved, DiaryStatus.organized):
        if diary.status == DiaryStatus.analyzed:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="已分析的日记不可重新整理，只能重新分析",
            )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="仅已保存或已整理的日记可以整理",
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
        current_step=task.current_step,
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
        diary = db.query(Diary).filter(Diary.id == diary_id, Diary.deleted_at.is_(None)).first()
        if diary:
            diary.status = DiaryStatus.organized

        # 更新任务状态
        task = db.query(OrganizeTask).filter(OrganizeTask.id == task_id).first()
        if task:
            task.status = "completed"
            task.current_step = None

        db.commit()

        # 清理 checkpoint 数据不应影响已提交的业务结果
        from services.pipeline import cleanup_checkpoint
        try:
            await cleanup_checkpoint(task_id)
        except Exception as cleanup_error:
            logging.getLogger(__name__).warning("清理整理 checkpoint 失败: %s", cleanup_error)
    except Exception as e:
        # 任务失败：日记保持 saved，记录错误
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
        .join(Diary, Diary.id == OrganizeTask.diary_id)
        .filter(
            OrganizeTask.diary_id == diary_id,
            OrganizeTask.user_id == current_user.id,
            OrganizeTask.task_type == "organize",
            Diary.deleted_at.is_(None),
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
        .filter(Diary.id == diary_id, Diary.user_id == current_user.id, Diary.deleted_at.is_(None))
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

    # 本次分析模式由当前有效反馈决定，并在任务创建后固定下来。
    current_run = get_current_analysis_run(db, diary.id)
    has_effective_feedback = bool(
        current_run and effective_feedback(db, current_run.id)
    )
    analysis_mode = "feedback" if has_effective_feedback else "ordinary"
    feedback_run_id = str(current_run.id) if has_effective_feedback else None
    feedback_source_run_id = str(current_run.id) if current_run else None

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
            OrganizeTask.analysis_mode == analysis_mode,
        )
        .order_by(OrganizeTask.created_at.desc())
        .first()
    )
    if failed_task:
        failed_task.status = "running"
        failed_task.error_message = None
        db.commit()
        db.refresh(failed_task)
        task = failed_task
    else:
        # 6. 创建新 OrganizeTask 记录（task_type=analyze）
        task = OrganizeTask(
            diary_id=diary_id,
            user_id=current_user.id,
            task_type="analyze",
            analysis_mode=analysis_mode,
            status="running",
            current_step="analysis_generating",
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
            analysis_mode=analysis_mode,
            feedback_run_id=feedback_run_id,
            feedback_source_run_id=feedback_source_run_id,
        )
    )

    # 9. 立即返回任务状态
    return OrganizeTaskResponse(
        diary_id=diary_id,
        status="running",
        task_type="analyze",
        current_step=task.current_step,
        error_message=None,
    )


async def _run_analyze(
    task_id: str,
    diary_id: str,
    user_id: str,
    diary_organized_id: str,
    original_text: str,
    structured_diary: dict,
    analysis_mode: str,
    feedback_run_id: str | None = None,
    feedback_source_run_id: str | None = None,
):
    """后台执行 AI 分析（独立 DB session）"""
    db = SessionLocal()
    try:
        if analysis_mode == "feedback":
            if not feedback_run_id:
                raise ValueError("反馈分析任务缺少上一轮分析结果")
            from services.analysis_pipeline import run_feedback_reanalysis_pipeline
            await run_feedback_reanalysis_pipeline(
                structured_diary=structured_diary,
                task_id=task_id,
                diary_id=diary_id,
                user_id=user_id,
                diary_organized_id=diary_organized_id,
                previous_run_id=feedback_run_id,
            )
        else:
            # 调用分析流水线（内部完成标签落库 + 结果存储 + 状态更新为 analyzed）
            await ai_service.analyze_diary(
                original_text=original_text,
                structured_diary=structured_diary,
                task_id=task_id,
                diary_id=diary_id,
                user_id=user_id,
                diary_organized_id=diary_organized_id,
                feedback_source_run_id=feedback_source_run_id,
            )

        # 更新任务状态
        task = db.query(OrganizeTask).filter(OrganizeTask.id == task_id).first()
        if task:
            task.status = "completed"
            task.current_step = None
        db.commit()
    except Exception as e:
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
        .join(Diary, Diary.id == OrganizeTask.diary_id)
        .filter(
            OrganizeTask.diary_id == diary_id,
            OrganizeTask.user_id == current_user.id,
            OrganizeTask.task_type == "analyze",
            Diary.deleted_at.is_(None),
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
        .filter(Diary.id == diary_id, Diary.user_id == current_user.id, Diary.deleted_at.is_(None))
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

    # ── 事件批量更新 ──
    if update_data.events is not None:
        existing_events = {e.id: e for e in organized.events}
        for event_data in update_data.events:
            event = existing_events.get(event_data.id)
            if not event:
                continue
            if event_data.event_title is not None:
                event.event_title = event_data.event_title
            if event_data.body is not None:
                event.body = json.dumps(event_data.body, ensure_ascii=False)
            if event_data.feeling is not None:
                event.feeling = json.dumps(event_data.feeling, ensure_ascii=False)
            if event_data.reflection is not None:
                event.reflection = json.dumps(event_data.reflection, ensure_ascii=False)

        # 重新生成 content
        events_for_render = []
        for e in organized.events:
            events_for_render.append({
                "title": e.event_title,
                "body": json.loads(e.body) if isinstance(e.body, str) else (e.body or []),
                "feeling": json.loads(e.feeling) if isinstance(e.feeling, str) else (e.feeling or []),
                "reflection": json.loads(e.reflection) if isinstance(e.reflection, str) else (e.reflection or []),
            })
        organized.content = render_diary_to_markdown(
            events=events_for_render,
            introduction=organized.introduction or "",
            trivia=json.loads(organized.trivia) if isinstance(organized.trivia, str) else (organized.trivia or []),
            plans=json.loads(organized.plans) if isinstance(organized.plans, str) else (organized.plans or []),
        )

    db.commit()
    db.refresh(organized)
    return serialize_organized(organized, get_current_analysis_run(db, diary.id), current_user.id)


@router.put("/{diary_id}/events/{event_id}", response_model=DiaryEventResponse)
def update_diary_event(
    diary_id: UUID,
    event_id: UUID,
    update_data: DiaryEventUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """更新单个事件内容（仅 organized 和 analyzed 状态）"""
    diary = (
        db.query(Diary)
        .filter(Diary.id == diary_id, Diary.user_id == current_user.id, Diary.deleted_at.is_(None))
        .first()
    )
    if not diary:
        raise HTTPException(status_code=404, detail="日记不存在")

    # 状态守卫：仅 organized 和 analyzed
    if diary.status not in (DiaryStatus.organized, DiaryStatus.analyzed):
        raise HTTPException(status_code=400, detail="当前状态不允许编辑事件")

    # 通过 diary_organized_id 关联查找事件
    event = (
        db.query(DiaryEvent)
        .filter(DiaryEvent.id == event_id, DiaryEvent.diary_organized_id == diary.organized.id)
        .first()
    )
    if not event:
        raise HTTPException(status_code=404, detail="事件不存在")

    # 仅更新内容字段，保护 event_tags、analysis、sort_order
    if update_data.event_title is not None:
        event.event_title = update_data.event_title
    if update_data.body is not None:
        event.body = json.dumps(update_data.body, ensure_ascii=False)
    if update_data.feeling is not None:
        event.feeling = json.dumps(update_data.feeling, ensure_ascii=False)
    if update_data.reflection is not None:
        event.reflection = json.dumps(update_data.reflection, ensure_ascii=False)

    # 重新生成 content（Markdown）
    organized = diary.organized
    events_for_render = []
    for e in organized.events:
        events_for_render.append({
            "title": e.event_title,
            "body": json.loads(e.body) if isinstance(e.body, str) else (e.body or []),
            "feeling": json.loads(e.feeling) if isinstance(e.feeling, str) else (e.feeling or []),
            "reflection": json.loads(e.reflection) if isinstance(e.reflection, str) else (e.reflection or []),
        })
    organized.content = render_diary_to_markdown(
        events=events_for_render,
        introduction=organized.introduction or "",
        trivia=json.loads(organized.trivia) if isinstance(organized.trivia, str) else (organized.trivia or []),
        plans=json.loads(organized.plans) if isinstance(organized.plans, str) else (organized.plans or []),
    )

    db.commit()
    db.refresh(event)
    return serialize_event(event, get_current_analysis_run(db, diary.id), current_user.id)


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
        .filter(Diary.id == diary_id, Diary.user_id == current_user.id, Diary.deleted_at.is_(None))
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
    return serialize_diary(diary, db, current_user.id)
