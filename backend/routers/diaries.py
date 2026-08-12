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
from models.diary import (
    AnalysisFeedback,
    AnalysisItem,
    AnalysisRun,
    Diary,
    DiaryAnnotation,
    DiaryAnnotationComment,
    DiaryEvent,
    DiaryOrganized,
    DiaryStatus,
)
from models.favorite import Favorite
from models.tag import EventTag, Tag, diary_tags
from models.transcription import TranscriptionBatch
from models.user import User
from schemas.diary import (
    DiaryCalendarItem,
    DiaryCreate,
    DiaryOrganizedResponse,
    DiaryOrganizedUpdate,
    DiaryResponse,
    DiaryTagsUpdate,
    DiaryUpdate,
    FavoriteResponse,
    AnalysisFeedbackResponse,
    AnalysisFeedbackUpsert,
    DiaryAnnotationCommentUpsert,
    DiaryAnnotationCreate,
    DiaryAnnotationResponse,
)
from schemas.search import SearchListResponse
from services.ai import ai_service
from services.analysis_history import (
    ALL_ANALYSIS_TYPES,
    build_run_response,
    build_sections,
    effective_feedback,
    get_current_analysis_run,
)
from services.search_service import search_diaries as search_diaries_service
from services.auth import get_current_user
from services.knowledge_guards import KnowledgeSourceLockedError, assert_knowledge_source_writable

import asyncio
from database import SessionLocal
from utils.diary_render import render_diary_to_markdown
from models.diary import DiaryCheckLog, DiaryCleanCheckLog, OrganizeTask
from schemas.diary import OrganizeTaskResponse, DiaryEventUpdate, DiaryEventResponse
from utils.log_context import Stopwatch, log_extra

router = APIRouter(prefix="/api/diaries", tags=["日记管理"])
logger = logging.getLogger(__name__)


def ensure_knowledge_source_writable(db: Session, diary_id: UUID) -> None:
    try:
        assert_knowledge_source_writable(db, diary_id)
    except KnowledgeSourceLockedError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


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


def is_diary_favorite(diary_id: UUID, user_id: UUID, db: Session) -> bool:
    return db.query(Favorite.id).filter(
        Favorite.user_id == user_id,
        Favorite.diary_id == diary_id,
    ).first() is not None


def is_event_favorite(event_id: UUID, user_id: UUID, db: Session) -> bool:
    return db.query(Favorite.id).filter(
        Favorite.user_id == user_id,
        Favorite.event_id == event_id,
    ).first() is not None


def serialize_event(event: DiaryEvent, current_run: AnalysisRun | None, user_id: UUID, db: Session) -> dict:
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
        "is_favorite": is_event_favorite(event.id, user_id, db),
        "ai_importance": event.ai_importance,
        "ai_importance_reason": event.ai_importance_reason,
        "user_importance": event.user_importance,
        "user_importance_reason": event.user_importance_reason,
        "importance_origin": event.importance_origin,
    }


def serialize_organized(organized: DiaryOrganized | None, current_run: AnalysisRun | None, user_id: UUID, db: Session) -> dict | None:
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
            serialize_event(event, current_run, user_id, db)
            for event in sorted(organized.events, key=lambda item: item.sort_order)
        ],
        "check_logs": organized.check_logs,
        "clean_check_logs": organized.clean_check_logs,
        "analysis": build_run_response(current_run, user_id),
    }


def serialize_diary(diary: Diary, db: Session, user_id: UUID) -> dict:
    current_run = get_current_analysis_run(db, diary.id)
    status_value = diary.status.value if hasattr(diary.status, "value") else str(diary.status)
    transcription_batch = db.query(TranscriptionBatch.status).filter(
        TranscriptionBatch.diary_id == diary.id,
    ).order_by(TranscriptionBatch.created_at.desc()).first()
    transcription_status = {
        "COLLECTING": "audio_uploaded",
        "QUEUED": "transcribing",
        "PROCESSING": "transcribing",
        "FINALIZING": "transcribing",
        "PARTIAL_FAILED": "partial_failed",
    }.get(transcription_batch[0]) if transcription_batch else None
    return {
        "id": diary.id,
        "user_id": diary.user_id,
        "original_text": diary.original_text,
        "diary_date": diary.diary_date,
        "status": status_value,
        "transcription_status": transcription_status,
        "is_dirty": diary.is_dirty,
        "deleted_at": diary.deleted_at,
        "deleted_by": diary.deleted_by,
        "created_at": diary.created_at,
        "updated_at": diary.updated_at,
        "organized": serialize_organized(diary.organized, current_run, user_id, db),
        "tags": diary.tags,
        "is_favorite": is_diary_favorite(diary.id, user_id, db),
    }


def serialize_annotation(annotation: DiaryAnnotation) -> dict:
    comments = [item for item in annotation.comments if item.deleted_at is None]
    comments.sort(key=lambda item: item.created_at)
    return {
        "id": annotation.id,
        "diary_id": annotation.diary_id,
        "target_type": annotation.target_type,
        "event_id": annotation.event_id,
        "field_name": annotation.field_name,
        "analysis_item_id": annotation.analysis_item_id,
        "start_paragraph": annotation.start_paragraph,
        "start_offset": annotation.start_offset,
        "end_paragraph": annotation.end_paragraph,
        "end_offset": annotation.end_offset,
        "selected_text": annotation.selected_text,
        "context_before": annotation.context_before,
        "context_after": annotation.context_after,
        "created_at": annotation.created_at,
        "updated_at": annotation.updated_at,
        "comments": comments,
    }


def get_owned_diary(diary_id: UUID, db: Session, current_user: User) -> Diary:
    diary = (
        db.query(Diary)
        .filter(
            Diary.id == diary_id,
            Diary.user_id == current_user.id,
            Diary.deleted_at.is_(None),
        )
        .first()
    )
    if not diary:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="日记不存在")
    return diary


def validate_annotation_target(
    data: DiaryAnnotationCreate,
    diary: Diary,
    db: Session,
) -> None:
    if data.start_paragraph < 0 or data.end_paragraph < 0:
        raise HTTPException(status_code=400, detail="批注段落位置无效")
    if data.start_offset < 0 or data.end_offset < 0:
        raise HTTPException(status_code=400, detail="批注字符位置无效")
    if data.end_paragraph < data.start_paragraph or (
        data.end_paragraph == data.start_paragraph
        and data.end_offset <= data.start_offset
    ):
        raise HTTPException(status_code=400, detail="批注选区不能为空")
    if not data.selected_text.strip():
        raise HTTPException(status_code=400, detail="批注内容不能为空")

    if data.target_type == "ANALYSIS_ITEM":
        if data.event_id or data.field_name:
            raise HTTPException(status_code=400, detail="AI 分析批注定位参数无效")
        item = (
            db.query(AnalysisItem)
            .join(AnalysisRun, AnalysisRun.id == AnalysisItem.analysis_run_id)
            .filter(
                AnalysisItem.id == data.analysis_item_id,
                AnalysisRun.diary_id == diary.id,
                AnalysisRun.status == "CURRENT",
            )
            .first()
        )
        if not item:
            raise HTTPException(status_code=404, detail="AI 分析内容不存在")
        return

    expected_field = {
        "EVENT_BODY": "body",
        "EVENT_FEELING": "feeling",
        "EVENT_REFLECTION": "reflection",
    }.get(data.target_type)
    if not expected_field or data.analysis_item_id:
        raise HTTPException(status_code=400, detail="批注类型无效")
    if data.field_name != expected_field or not data.event_id:
        raise HTTPException(status_code=400, detail="事件批注定位参数无效")
    if not diary.organized:
        raise HTTPException(status_code=400, detail="日记尚未整理，无法添加事件批注")
    event = (
        db.query(DiaryEvent)
        .filter(
            DiaryEvent.id == data.event_id,
            DiaryEvent.diary_organized_id == diary.organized.id,
        )
        .first()
    )
    if not event:
        raise HTTPException(status_code=404, detail="事件不存在")


def annotation_source_matches(annotation: DiaryAnnotation, data: DiaryAnnotationCreate) -> bool:
    return (
        annotation.target_type == data.target_type
        and str(annotation.event_id or "") == str(data.event_id or "")
        and annotation.field_name == data.field_name
        and str(annotation.analysis_item_id or "") == str(data.analysis_item_id or "")
    )


def compare_annotation_point(paragraph: int, offset: int, other_paragraph: int, other_offset: int) -> int:
    return (paragraph - other_paragraph) or (offset - other_offset)


def annotation_contains(annotation: DiaryAnnotation, data: DiaryAnnotationCreate) -> bool:
    return (
        compare_annotation_point(annotation.start_paragraph, annotation.start_offset, data.start_paragraph, data.start_offset) <= 0
        and compare_annotation_point(annotation.end_paragraph, annotation.end_offset, data.end_paragraph, data.end_offset) >= 0
    )


def annotations_overlap(annotation: DiaryAnnotation, data: DiaryAnnotationCreate) -> bool:
    return not (
        compare_annotation_point(annotation.end_paragraph, annotation.end_offset, data.start_paragraph, data.start_offset) <= 0
        or compare_annotation_point(data.end_paragraph, data.end_offset, annotation.start_paragraph, annotation.start_offset) <= 0
    )


def annotation_overlaps_range(
    annotation: DiaryAnnotation,
    start_paragraph: int,
    start_offset: int,
    end_paragraph: int,
    end_offset: int,
) -> bool:
    return not (
        compare_annotation_point(annotation.end_paragraph, annotation.end_offset, start_paragraph, start_offset) <= 0
        or compare_annotation_point(end_paragraph, end_offset, annotation.start_paragraph, annotation.start_offset) <= 0
    )


def annotation_union_text(annotations: list[DiaryAnnotation], data: DiaryAnnotationCreate) -> str:
    """返回合并后可用的选中文本；定位范围才是渲染的权威数据。"""
    for item in annotations:
        if (
            item.start_paragraph == data.start_paragraph
            and item.start_offset == data.start_offset
            and item.end_paragraph == data.end_paragraph
            and item.end_offset == data.end_offset
        ):
            return item.selected_text
    return data.selected_text


def merge_annotation_ranges(
    db: Session,
    diary: Diary,
    data: DiaryAnnotationCreate,
    current_user: User,
) -> DiaryAnnotation | None:
    active = (
        db.query(DiaryAnnotation)
        .filter(
            DiaryAnnotation.diary_id == diary.id,
            DiaryAnnotation.deleted_at.is_(None),
        )
        .all()
    )
    candidates = [item for item in active if annotation_source_matches(item, data)]
    overlapping = [item for item in candidates if annotations_overlap(item, data)]
    # 以当前并集为边界继续吸收相交划线，保证历史上已有的多条重叠数据也会归并。
    while overlapping:
        start_paragraph = min(
            [data.start_paragraph] + [item.start_paragraph for item in overlapping],
        )
        start_offset = min(
            item.start_offset if item.start_paragraph == start_paragraph else data.start_offset
            for item in overlapping + [data]
            if item.start_paragraph == start_paragraph
        )
        end_paragraph = max(
            [data.end_paragraph] + [item.end_paragraph for item in overlapping],
        )
        end_offset = max(
            item.end_offset if item.end_paragraph == end_paragraph else data.end_offset
            for item in overlapping + [data]
            if item.end_paragraph == end_paragraph
        )
        additional = [
            item for item in candidates
            if item not in overlapping
            and annotation_overlaps_range(item, start_paragraph, start_offset, end_paragraph, end_offset)
        ]
        if not additional:
            break
        overlapping.extend(additional)

    containing = next((item for item in overlapping if annotation_contains(item, data)), None)
    if containing and len(overlapping) == 1:
        if data.comment and data.comment.strip():
            db.add(DiaryAnnotationComment(annotation_id=containing.id, content=data.comment.strip()))
        return containing

    if not overlapping:
        return None

    all_items = overlapping
    start_item = min(
        all_items,
        key=lambda item: (item.start_paragraph, item.start_offset),
    )
    end_item = max(
        all_items,
        key=lambda item: (item.end_paragraph, item.end_offset),
    )
    start_paragraph = min(item.start_paragraph for item in all_items + [data])
    start_offset = (
        data.start_offset if data.start_paragraph == start_paragraph
        else start_item.start_offset
    )
    if start_item.start_paragraph == start_paragraph:
        start_offset = min(start_offset, start_item.start_offset)
    end_paragraph = max(item.end_paragraph for item in all_items + [data])
    end_offset = (
        data.end_offset if data.end_paragraph == end_paragraph
        else end_item.end_offset
    )
    if end_item.end_paragraph == end_paragraph:
        end_offset = max(end_offset, end_item.end_offset)

    survivor = start_item
    survivor.start_paragraph = start_paragraph
    survivor.start_offset = start_offset
    survivor.end_paragraph = end_paragraph
    survivor.end_offset = end_offset
    survivor.selected_text = annotation_union_text(overlapping, data)
    survivor.context_before = data.context_before
    survivor.context_after = data.context_after
    survivor.updated_at = datetime.utcnow()

    now = datetime.utcnow()
    for item in overlapping:
        if item.id == survivor.id:
            continue
        comments = (
            db.query(DiaryAnnotationComment)
            .filter(
                DiaryAnnotationComment.annotation_id == item.id,
                DiaryAnnotationComment.deleted_at.is_(None),
            )
            .all()
        )
        for comment in comments:
            comment.annotation_id = survivor.id
            comment.updated_at = now
        item.deleted_at = now
        item.deleted_by = current_user.id
        item.deleted_reason = "merged"
        item.merged_into_id = survivor.id
        item.updated_at = now
    if data.comment and data.comment.strip():
        db.add(DiaryAnnotationComment(annotation_id=survivor.id, content=data.comment.strip()))
    return survivor


def soft_delete_event_annotations(
    db: Session,
    event_id: UUID,
    fields: set[str],
    user_id: UUID,
    reason: str = "content_changed",
) -> None:
    if not fields:
        return
    annotations = (
        db.query(DiaryAnnotation)
        .filter(
            DiaryAnnotation.event_id == event_id,
            DiaryAnnotation.field_name.in_(fields),
            DiaryAnnotation.deleted_at.is_(None),
        )
        .all()
    )
    now = datetime.utcnow()
    for annotation in annotations:
        annotation.deleted_at = now
        annotation.deleted_by = user_id
        annotation.deleted_reason = reason
        annotation.updated_at = now


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
    limit: Optional[int] = Query(None, ge=1, le=100),
    offset: int = Query(0, ge=0),
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
    if limit is not None:
        query = query.offset(offset).limit(limit)
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


@router.get("/search", response_model=SearchListResponse)
def search_diaries(
    q: str = Query(..., min_length=1, description="搜索关键词（必填，至少 1 个字符）"),
    start_date: Optional[date] = Query(None, description="起始日期 YYYY-MM-DD（基于 diary.diary_date）"),
    end_date: Optional[date] = Query(None, description="结束日期 YYYY-MM-DD（基于 diary.diary_date）"),
    limit: int = Query(20, ge=1, le=100, description="每页数量"),
    offset: int = Query(0, ge=0, description="偏移量"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """统一搜索：按日记聚合关键词与语义命中，分页返回日记结果卡。

    检索范围：DiaryEvent 的 event_title/body/feeling/reflection + 关联 EVENT 作用域
    analysis_items 的 content/question。按 user_id 隔离、过滤 status∈(organized,analyzed)、
    过滤软删除、按所属 diary.diary_date 做日期范围筛选。

    关键词严格大小写不敏感子串匹配；语义服务不可用时仍返回关键词结果。
    """
    # 日期范围校验（start_date 不能晚于 end_date）
    if start_date and end_date and start_date > end_date:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="start_date 不能晚于 end_date",
        )

    items, total, semantic_status = search_diaries_service(
        db=db,
        user_id=current_user.id,
        q=q,
        start_date=start_date,
        end_date=end_date,
        limit=limit,
        offset=offset,
    )
    return SearchListResponse(items=items, total=total, semantic_status=semantic_status)


def serialize_favorite(favorite: Favorite, db: Session, user_id: UUID) -> dict:
    """将收藏统一转换为日记或事件列表项。"""
    if favorite.diary_id:
        diary = favorite.diary
        event = None
        favorite_type = "diary"
    else:
        event = favorite.event
        diary = event.organized.diary if event and event.organized else None
        favorite_type = "event"

    if diary is None:
        raise ValueError("收藏目标缺少所属日记")

    current_run = get_current_analysis_run(db, diary.id)
    return {
        "id": favorite.id,
        "favorite_type": favorite_type,
        "created_at": favorite.created_at,
        "diary": serialize_diary(diary, db, user_id),
        "event": serialize_event(event, current_run, user_id, db) if event else None,
    }


@router.get("/favorites", response_model=list[FavoriteResponse])
def list_favorites(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """获取当前用户收藏的日记与事件，按所属日记日期倒序排列。"""
    favorites = (
        db.query(Favorite)
        .filter(Favorite.user_id == current_user.id)
        .all()
    )

    valid_favorites: list[tuple[Favorite, Diary]] = []
    for favorite in favorites:
        diary = favorite.diary if favorite.diary_id else (
            favorite.event.organized.diary if favorite.event and favorite.event.organized else None
        )
        if diary and diary.deleted_at is None:
            valid_favorites.append((favorite, diary))

    valid_favorites.sort(
        key=lambda item: (item[1].diary_date, item[0].created_at),
        reverse=True,
    )
    return [serialize_favorite(favorite, db, current_user.id) for favorite, _ in valid_favorites]


@router.put("/{diary_id}/favorite", status_code=status.HTTP_204_NO_CONTENT)
def favorite_diary(
    diary_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """收藏日记；重复请求保持幂等。"""
    get_owned_diary(diary_id, db, current_user)
    existing = db.query(Favorite.id).filter(
        Favorite.user_id == current_user.id,
        Favorite.diary_id == diary_id,
    ).first()
    if not existing:
        db.add(Favorite(user_id=current_user.id, diary_id=diary_id))
        db.commit()


@router.delete("/{diary_id}/favorite", status_code=status.HTTP_204_NO_CONTENT)
def unfavorite_diary(
    diary_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """取消收藏日记；目标不存在或未收藏时均返回成功。"""
    db.query(Favorite).filter(
        Favorite.user_id == current_user.id,
        Favorite.diary_id == diary_id,
    ).delete(synchronize_session=False)
    db.commit()


@router.put("/{diary_id}/events/{event_id}/favorite", status_code=status.HTTP_204_NO_CONTENT)
def favorite_event(
    diary_id: UUID,
    event_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """收藏日记内事件；重复请求保持幂等。"""
    diary = get_owned_diary(diary_id, db, current_user)
    event = (
        db.query(DiaryEvent)
        .filter(DiaryEvent.id == event_id, DiaryEvent.diary_organized_id == diary.organized.id)
        .first()
        if diary.organized else None
    )
    if not event:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="事件不存在")
    existing = db.query(Favorite.id).filter(
        Favorite.user_id == current_user.id,
        Favorite.event_id == event_id,
    ).first()
    if not existing:
        db.add(Favorite(user_id=current_user.id, event_id=event_id))
        db.commit()


@router.delete("/{diary_id}/events/{event_id}/favorite", status_code=status.HTTP_204_NO_CONTENT)
def unfavorite_event(
    diary_id: UUID,
    event_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """取消收藏事件；目标不存在或未收藏时均返回成功。"""
    db.query(Favorite).filter(
        Favorite.user_id == current_user.id,
        Favorite.event_id == event_id,
    ).delete(synchronize_session=False)
    db.commit()


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


# ─────────────────── 日记批注 ───────────────────


@router.get("/{diary_id}/annotations", response_model=list[DiaryAnnotationResponse])
def list_diary_annotations(
    diary_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """获取当前日记中仍有效的划线批注。"""
    get_owned_diary(diary_id, db, current_user)
    annotations = (
        db.query(DiaryAnnotation)
        .filter(
            DiaryAnnotation.diary_id == diary_id,
            DiaryAnnotation.deleted_at.is_(None),
            or_(
                DiaryAnnotation.target_type != "ANALYSIS_ITEM",
                DiaryAnnotation.analysis_item_id.in_(
                    db.query(AnalysisItem.id)
                    .join(AnalysisRun, AnalysisRun.id == AnalysisItem.analysis_run_id)
                    .filter(
                        AnalysisRun.diary_id == diary_id,
                        AnalysisRun.status == "CURRENT",
                    )
                ),
            ),
        )
        .order_by(DiaryAnnotation.created_at)
        .all()
    )
    return [serialize_annotation(item) for item in annotations]


@router.post("/{diary_id}/annotations", response_model=DiaryAnnotationResponse, status_code=status.HTTP_201_CREATED)
def create_diary_annotation(
    diary_id: UUID,
    annotation_data: DiaryAnnotationCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """创建一条划线，可在同一事务中创建评论。"""
    diary = get_owned_diary(diary_id, db, current_user)
    validate_annotation_target(annotation_data, diary, db)
    existing = merge_annotation_ranges(db, diary, annotation_data, current_user)
    if existing:
        db.commit()
        db.refresh(existing)
        return serialize_annotation(existing)
    annotation = DiaryAnnotation(
        diary_id=diary.id,
        target_type=annotation_data.target_type,
        event_id=annotation_data.event_id,
        field_name=annotation_data.field_name,
        analysis_item_id=annotation_data.analysis_item_id,
        start_paragraph=annotation_data.start_paragraph,
        start_offset=annotation_data.start_offset,
        end_paragraph=annotation_data.end_paragraph,
        end_offset=annotation_data.end_offset,
        selected_text=annotation_data.selected_text,
        context_before=annotation_data.context_before,
        context_after=annotation_data.context_after,
    )
    db.add(annotation)
    db.flush()
    if annotation_data.comment and annotation_data.comment.strip():
        db.add(
            DiaryAnnotationComment(
                annotation_id=annotation.id,
                content=annotation_data.comment.strip(),
            )
        )
    db.commit()
    db.refresh(annotation)
    return serialize_annotation(annotation)


@router.post(
    "/{diary_id}/annotations/{annotation_id}/comments",
    response_model=DiaryAnnotationResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_diary_annotation_comment(
    diary_id: UUID,
    annotation_id: UUID,
    comment_data: DiaryAnnotationCommentUpsert,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """为划线新增评论。"""
    diary = get_owned_diary(diary_id, db, current_user)
    content = comment_data.content.strip()
    if not content:
        raise HTTPException(status_code=400, detail="评论内容不能为空")
    annotation = (
        db.query(DiaryAnnotation)
        .filter(
            DiaryAnnotation.id == annotation_id,
            DiaryAnnotation.diary_id == diary.id,
            DiaryAnnotation.deleted_at.is_(None),
        )
        .first()
    )
    if not annotation:
        raise HTTPException(status_code=404, detail="批注不存在")
    db.add(DiaryAnnotationComment(annotation_id=annotation.id, content=content))
    db.commit()
    db.refresh(annotation)
    return serialize_annotation(annotation)


@router.put(
    "/{diary_id}/annotations/{annotation_id}/comments/{comment_id}",
    response_model=DiaryAnnotationResponse,
)
def update_diary_annotation_comment(
    diary_id: UUID,
    annotation_id: UUID,
    comment_id: UUID,
    comment_data: DiaryAnnotationCommentUpsert,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """新增或修改划线评论。"""
    diary = get_owned_diary(diary_id, db, current_user)
    content = comment_data.content.strip()
    if not content:
        raise HTTPException(status_code=400, detail="评论内容不能为空")
    annotation = (
        db.query(DiaryAnnotation)
        .filter(
            DiaryAnnotation.id == annotation_id,
            DiaryAnnotation.diary_id == diary.id,
            DiaryAnnotation.deleted_at.is_(None),
        )
        .first()
    )
    if not annotation:
        raise HTTPException(status_code=404, detail="批注不存在")
    comment = next(
        (
            item for item in annotation.comments
            if item.id == comment_id and item.deleted_at is None
        ),
        None,
    )
    if not comment:
        raise HTTPException(status_code=404, detail="评论不存在")
    comment.content = content
    comment.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(annotation)
    return serialize_annotation(annotation)


@router.delete(
    "/{diary_id}/annotations/{annotation_id}/comments/{comment_id}",
    response_model=DiaryAnnotationResponse,
)
def delete_diary_annotation_comment(
    diary_id: UUID,
    annotation_id: UUID,
    comment_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """逻辑删除评论，划线本身继续保留。"""
    diary = get_owned_diary(diary_id, db, current_user)
    annotation = (
        db.query(DiaryAnnotation)
        .filter(
            DiaryAnnotation.id == annotation_id,
            DiaryAnnotation.diary_id == diary.id,
            DiaryAnnotation.deleted_at.is_(None),
        )
        .first()
    )
    if not annotation:
        raise HTTPException(status_code=404, detail="批注不存在")
    now = datetime.utcnow()
    comment = next(
        (
            item for item in annotation.comments
            if item.id == comment_id and item.deleted_at is None
        ),
        None,
    )
    if not comment:
        raise HTTPException(status_code=404, detail="评论不存在")
    comment.deleted_at = now
    comment.deleted_by = current_user.id
    comment.deleted_reason = "comment_deleted"
    comment.updated_at = now
    db.commit()
    db.refresh(annotation)
    return serialize_annotation(annotation)


@router.delete("/{diary_id}/annotations/{annotation_id}", response_model=DiaryAnnotationResponse)
def delete_diary_annotation(
    diary_id: UUID,
    annotation_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """逻辑删除划线，保留评论历史记录。"""
    diary = get_owned_diary(diary_id, db, current_user)
    annotation = (
        db.query(DiaryAnnotation)
        .filter(
            DiaryAnnotation.id == annotation_id,
            DiaryAnnotation.diary_id == diary.id,
            DiaryAnnotation.deleted_at.is_(None),
        )
        .first()
    )
    if not annotation:
        raise HTTPException(status_code=404, detail="批注不存在")
    if any(comment.deleted_at is None for comment in annotation.comments):
        raise HTTPException(status_code=409, detail="请先删除划线上的全部评论")
    now = datetime.utcnow()
    annotation.deleted_at = now
    annotation.deleted_by = current_user.id
    annotation.deleted_reason = "annotation_deleted"
    annotation.updated_at = now
    db.commit()
    db.refresh(annotation)
    return serialize_annotation(annotation)


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

    running_organize_task = (
        db.query(OrganizeTask)
        .filter(
            OrganizeTask.diary_id == diary_id,
            OrganizeTask.user_id == current_user.id,
            OrganizeTask.task_type == "organize",
            OrganizeTask.status == "running",
        )
        .first()
    )
    if running_organize_task:
        raise HTTPException(
            status_code=400,
            detail="当前正在整理，暂不能修改原文",
        )

    # 状态守卫：仅 saved、organized 可编辑原文
    if diary.status not in (DiaryStatus.saved, DiaryStatus.organized):
        raise HTTPException(
            status_code=400,
            detail="当前状态不允许编辑原文",
        )

    # 仅更新非 None 字段
    source_changed = False
    if update_data.original_text is not None and update_data.original_text != diary.original_text:
        diary.original_text = update_data.original_text
        source_changed = True
    if update_data.diary_date is not None and update_data.diary_date != diary.diary_date:
        diary.diary_date = update_data.diary_date
        source_changed = True
    if source_changed:
        diary.content_revision += 1
        diary.is_dirty = True

    # 兼容调用方显式设置脏标记
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
        .with_for_update()
        .first()
    )
    if not diary:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="日记不存在")
    if diary.status == DiaryStatus.analyzed:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="已分析的日记不可删除")
    ensure_knowledge_source_writable(db, diary.id)

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
    db.query(Favorite).filter(Favorite.diary_id == diary_id).delete(synchronize_session=False)
    event_ids = db.query(DiaryEvent.id).filter(
        DiaryEvent.diary_organized_id == diary.organized.id
    ) if diary.organized else []
    if diary.organized:
        db.query(Favorite).filter(Favorite.event_id.in_(event_ids)).delete(synchronize_session=False)
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
        .with_for_update()
        .first()
    )
    if not diary:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="日记不存在")
    ensure_knowledge_source_writable(db, diary.id)

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
        _run_organize(str(task.id), str(diary_id), diary.original_text, str(current_user.id), diary.diary_date.isoformat())
    )

    # 7. 立即返回任务状态
    return OrganizeTaskResponse(
        diary_id=diary_id,
        status="running",
        task_type="organize",
        current_step=task.current_step,
        error_message=None,
    )


async def _run_organize(task_id: str, diary_id: str, original_text: str, user_id: str, diary_date: str):
    """后台执行 AI 整理（独立 DB session）"""
    db = SessionLocal()
    try:
        # 调用 AI 服务（LangGraph 流水线，进度由 Node 内部更新）
        result = await ai_service.organize_diary(
            original_text, task_id=task_id, diary_id=diary_id, user_id=user_id, diary_date=diary_date
        )

        # 生成 content markdown
        content = render_diary_to_markdown(
            events=result["events"],
            introduction=result.get("introduction", ""),
            trivia=result.get("trivia"),
            plans=result.get("plans"),
        )

        diary = db.query(Diary).filter(
            Diary.id == diary_id,
            Diary.deleted_at.is_(None),
        ).with_for_update().first()
        if not diary:
            raise RuntimeError("日记不存在或已删除")
        assert_knowledge_source_writable(db, diary.id)

        # 已整理日记再次整理时复用一对一的整理记录，并清除会被替换的旧事件。
        organized = db.query(DiaryOrganized).filter(DiaryOrganized.diary_id == diary_id).first()
        if organized:
            organized.structured_revision += 1
            old_event_ids = [event.id for event in organized.events]
            if old_event_ids:
                annotation_ids = [item[0] for item in db.query(DiaryAnnotation.id).filter(
                    DiaryAnnotation.event_id.in_(old_event_ids)
                ).all()]
                if annotation_ids:
                    db.query(DiaryAnnotationComment).filter(
                        DiaryAnnotationComment.annotation_id.in_(annotation_ids)
                    ).delete(synchronize_session=False)
                    db.query(DiaryAnnotation).filter(
                        DiaryAnnotation.id.in_(annotation_ids)
                    ).delete(synchronize_session=False)
                db.query(Favorite).filter(Favorite.event_id.in_(old_event_ids)).delete(synchronize_session=False)
                db.query(EventTag).filter(EventTag.diary_event_id.in_(old_event_ids)).delete(synchronize_session=False)
                db.query(DiaryEvent).filter(DiaryEvent.id.in_(old_event_ids)).delete(synchronize_session=False)
            db.query(DiaryCheckLog).filter(
                DiaryCheckLog.diary_organized_id == organized.id
            ).delete(synchronize_session=False)
            db.query(DiaryCleanCheckLog).filter(
                DiaryCleanCheckLog.diary_organized_id == organized.id
            ).delete(synchronize_session=False)
            organized.task_id = task_id
            organized.title = result["title"]
            organized.summary = result["summary"]
            organized.content = content
            organized.location = result["location"]
            organized.introduction = result.get("introduction", "")
            organized.trivia = json.dumps(result.get("trivia", []), ensure_ascii=False)
            organized.plans = json.dumps(result.get("plans", []), ensure_ascii=False)
            organized.source_content_revision = diary.content_revision
        else:
            organized = DiaryOrganized(
                task_id=task_id,
                diary_id=diary_id,
                source_content_revision=diary.content_revision,
                structured_revision=1,
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

        # 创建 DiaryEvent 记录（事件标签由分析阶段产出，重要性由整理阶段产出）
        new_events: list[DiaryEvent] = []
        for i, event in enumerate(result["events"]):
            event_title = event.get("title", "未命名事件")
            diary_event = DiaryEvent(
                diary_organized_id=organized.id,
                event_title=event_title,
                body=json.dumps(event.get("body", []), ensure_ascii=False),
                feeling=json.dumps(event.get("feeling", []), ensure_ascii=False),
                reflection=json.dumps(event.get("reflection", []), ensure_ascii=False),
                event_tags=json.dumps({}, ensure_ascii=False),
                sort_order=i,
                ai_importance=event.get("importance", "LOW"),
                ai_importance_reason=event.get("importance_reason", "未识别到明确的用户影响"),
                importance_origin="DIARY_ORGANIZE",
                importance_updated_at=datetime.utcnow(),
            )
            db.add(diary_event)
            new_events.append(diary_event)

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
        diary.status = DiaryStatus.organized
        diary.is_dirty = False

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
        analysis_mode=task.analysis_mode,
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
    request_started = Stopwatch()
    logger.info(
        "收到 AI 日记分析请求",
        extra=log_extra(event="analysis.request.received", diary_id=str(diary_id), user_id=str(current_user.id)),
    )
    # 1. 查找日记，校验属于当前用户
    diary = (
        db.query(Diary)
        .filter(Diary.id == diary_id, Diary.user_id == current_user.id, Diary.deleted_at.is_(None))
        .with_for_update()
        .first()
    )
    if not diary:
        logger.warning(
            "AI 日记分析请求被拒绝：日记不存在",
            extra=log_extra(event="analysis.request.rejected", diary_id=str(diary_id), user_id=str(current_user.id), reason="diary_not_found"),
        )
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="日记不存在")
    ensure_knowledge_source_writable(db, diary.id)

    # 2. 状态守卫：仅 organized、analyzed 可触发分析
    if diary.status not in (DiaryStatus.organized, DiaryStatus.analyzed):
        logger.warning(
            "AI 日记分析请求被拒绝：日记状态不允许",
            extra=log_extra(event="analysis.request.rejected", diary_id=str(diary_id), user_id=str(current_user.id), reason="invalid_diary_status", status=diary.status.value),
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="仅已整理或已分析的日记可以触发分析",
        )

    # 3. 必须有整理记录才能分析
    if not diary.organized:
        logger.warning(
            "AI 日记分析请求被拒绝：缺少整理结果",
            extra=log_extra(event="analysis.request.rejected", diary_id=str(diary_id), user_id=str(current_user.id), reason="organized_result_missing"),
        )
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
    logger.info(
        "AI 日记分析分支已确定",
        extra=log_extra(
            event="analysis.branch.selected",
            diary_id=str(diary_id),
            user_id=str(current_user.id),
            analysis_mode=analysis_mode,
            feedback_source_run_id=feedback_source_run_id,
            has_effective_feedback=has_effective_feedback,
        ),
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
            logger.warning(
                "超时分析任务已终止",
                extra=log_extra(
                    event="analysis.task.timed_out",
                    diary_id=str(diary_id),
                    task_id=str(existing_task.id),
                    analysis_mode=existing_task.analysis_mode,
                    old_status="running",
                    new_status="failed",
                ),
            )
        else:
            logger.info(
                "复用正在运行的分析任务",
                extra=log_extra(event="analysis.task.reused", diary_id=str(diary_id), task_id=str(existing_task.id), status=existing_task.status, current_step=existing_task.current_step),
            )
            return OrganizeTaskResponse(
                diary_id=diary_id,
                status=existing_task.status,
                task_type="analyze",
                analysis_mode=existing_task.analysis_mode,
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
        logger.info(
            "失败分析任务已重新启动",
            extra=log_extra(event="analysis.task.restarted", diary_id=str(diary_id), task_id=str(task.id), analysis_mode=analysis_mode, old_status="failed", new_status="running"),
        )
    else:
        # 6. 创建新 OrganizeTask 记录（task_type=analyze）
        task = OrganizeTask(
            diary_id=diary_id,
            user_id=current_user.id,
            task_type="analyze",
            analysis_mode=analysis_mode,
            status="running",
            current_step="feedback_core_analysis" if analysis_mode == "feedback" else "mood_tag_extract",
        )
        db.add(task)
        db.commit()
        db.refresh(task)
        logger.info(
            "分析任务已创建",
            extra=log_extra(event="analysis.task.created", diary_id=str(diary_id), task_id=str(task.id), user_id=str(current_user.id), analysis_mode=analysis_mode, status=task.status, current_step=task.current_step),
        )

    # 7. 组装 structured_diary，供分析流水线使用
    diary_organized = diary.organized
    structured_diary = {
        "diary_date": diary.diary_date.isoformat(),
        "analysis_date": date.today().isoformat(),
        "timezone": "Asia/Shanghai",
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
        ),
        name=f"analysis-{task.id}",
    )
    logger.info(
        "后台分析任务已启动",
        extra=log_extra(event="analysis.task.started", diary_id=str(diary_id), task_id=str(task.id), analysis_mode=analysis_mode, event_count=len(structured_diary["events"]), duration_ms=request_started.elapsed_ms()),
    )

    # 9. 立即返回任务状态
    return OrganizeTaskResponse(
        diary_id=diary_id,
        status="running",
        task_type="analyze",
        analysis_mode=task.analysis_mode,
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
    task_started = Stopwatch()
    db = SessionLocal()
    logger.info(
        "后台分析任务开始执行",
        extra=log_extra(event="analysis.background.started", diary_id=diary_id, task_id=task_id, analysis_mode=analysis_mode, feedback_source_run_id=feedback_source_run_id),
    )
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

        # 分析产出认知 / 理解层，增量重算该日记全部事件的语义向量（fail-open）。
        sync_events = (
            db.query(DiaryEvent.id)
            .filter(DiaryEvent.diary_organized_id == diary_organized_id)
            .all()
        )
        logger.info(
            "后台分析任务完成",
            extra=log_extra(event="analysis.task.completed", diary_id=diary_id, task_id=task_id, analysis_mode=analysis_mode, old_status="running", new_status="completed", duration_ms=task_started.elapsed_ms()),
        )
    except Exception as e:
        logger.exception(
            "后台分析任务失败",
            extra=log_extra(event="analysis.task.failed", diary_id=diary_id, task_id=task_id, analysis_mode=analysis_mode, error_type=type(e).__name__, duration_ms=task_started.elapsed_ms()),
        )
        db.rollback()
        task = db.query(OrganizeTask).filter(OrganizeTask.id == task_id).first()
        if task:
            task.status = "failed"
            task.error_message = str(e)
        db.commit()
        logger.info(
            "后台分析任务失败状态已保存",
            extra=log_extra(event="analysis.task.failure_persisted", diary_id=diary_id, task_id=task_id, new_status="failed"),
        )
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
        analysis_mode=task.analysis_mode,
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
        .with_for_update()
        .first()
    )
    if not diary:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="日记不存在")
    ensure_knowledge_source_writable(db, diary.id)
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
    structured_changed = False
    # 仅更新提供的字段（非 None）
    if update_data.title is not None and update_data.title != organized.title:
        structured_changed = True
        organized.title = update_data.title
    if update_data.summary is not None and update_data.summary != organized.summary:
        structured_changed = True
        organized.summary = update_data.summary
    if update_data.content is not None and update_data.content != organized.content:
        structured_changed = True
        organized.content = update_data.content
    if update_data.mood is not None and update_data.mood != organized.mood:
        structured_changed = True
        organized.mood = update_data.mood
    if update_data.location is not None and update_data.location != organized.location:
        structured_changed = True
        organized.location = update_data.location
    if update_data.introduction is not None and update_data.introduction != organized.introduction:
        structured_changed = True
        organized.introduction = update_data.introduction
    if update_data.trivia is not None:
        if parse_json_value(organized.trivia, []) != update_data.trivia:
            structured_changed = True
        organized.trivia = json.dumps(update_data.trivia, ensure_ascii=False)
    if update_data.plans is not None:
        if parse_json_value(organized.plans, []) != update_data.plans:
            structured_changed = True
        organized.plans = json.dumps(update_data.plans, ensure_ascii=False)

    # ── 事件批量更新 ──
    if update_data.events is not None:
        existing_events = {e.id: e for e in organized.events}
        for event_data in update_data.events:
            event = existing_events.get(event_data.id)
            if not event:
                continue
            changed_fields: set[str] = set()
            if event_data.event_title is not None:
                if event.event_title != event_data.event_title:
                    structured_changed = True
                event.event_title = event_data.event_title
            if event_data.body is not None:
                if parse_json_value(event.body, []) != event_data.body:
                    changed_fields.add("body")
                    structured_changed = True
                event.body = json.dumps(event_data.body, ensure_ascii=False)
            if event_data.feeling is not None:
                if parse_json_value(event.feeling, []) != event_data.feeling:
                    changed_fields.add("feeling")
                    structured_changed = True
                event.feeling = json.dumps(event_data.feeling, ensure_ascii=False)
            if event_data.reflection is not None:
                if parse_json_value(event.reflection, []) != event_data.reflection:
                    changed_fields.add("reflection")
                    structured_changed = True
                event.reflection = json.dumps(event_data.reflection, ensure_ascii=False)
            if "user_importance" in event_data.model_fields_set:
                event.user_importance = event_data.user_importance
                event.user_importance_reason = event_data.user_importance_reason
                event.importance_updated_at = datetime.utcnow()
            soft_delete_event_annotations(db, event.id, changed_fields, current_user.id)

    if structured_changed:
        organized.structured_revision += 1
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
    return serialize_organized(organized, get_current_analysis_run(db, diary.id), current_user.id, db)


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
        .with_for_update()
        .first()
    )
    if not diary:
        raise HTTPException(status_code=404, detail="日记不存在")
    ensure_knowledge_source_writable(db, diary.id)

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

    changed_fields: set[str] = set()
    structured_changed = False
    # 仅更新内容字段，保护 event_tags、analysis、sort_order
    if update_data.event_title is not None:
        if event.event_title != update_data.event_title:
            structured_changed = True
        event.event_title = update_data.event_title
    if update_data.body is not None:
        if parse_json_value(event.body, []) != update_data.body:
            changed_fields.add("body")
            structured_changed = True
        event.body = json.dumps(update_data.body, ensure_ascii=False)
    if update_data.feeling is not None:
        if parse_json_value(event.feeling, []) != update_data.feeling:
            changed_fields.add("feeling")
            structured_changed = True
        event.feeling = json.dumps(update_data.feeling, ensure_ascii=False)
    if update_data.reflection is not None:
        if parse_json_value(event.reflection, []) != update_data.reflection:
            changed_fields.add("reflection")
            structured_changed = True
        event.reflection = json.dumps(update_data.reflection, ensure_ascii=False)
    if "user_importance" in update_data.model_fields_set:
        event.user_importance = update_data.user_importance
        event.user_importance_reason = update_data.user_importance_reason
        event.importance_updated_at = datetime.utcnow()
    soft_delete_event_annotations(db, event.id, changed_fields, current_user.id)

    organized = diary.organized
    if structured_changed:
        # 重新生成 content（Markdown）
        organized.structured_revision += 1
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
    return serialize_event(event, get_current_analysis_run(db, diary.id), current_user.id, db)


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
