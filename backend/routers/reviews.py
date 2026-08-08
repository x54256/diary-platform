"""定期回顾 API。"""

from __future__ import annotations

import copy
import base64
from datetime import datetime, timedelta
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import and_, case, func, or_
from sqlalchemy.orm import Session, joinedload

from database import get_db
from models.review import (
    Review,
    ReviewDailyDigest,
    ReviewAction,
    ReviewActionCheck,
    ReviewActionStatus,
    ReviewFeedback,
    ReviewGenerationMode,
    ReviewPeriodRole,
    ReviewSource,
    ReviewSourceSet,
    ReviewSourceSetItem,
    ReviewSourceSetStatus,
    ReviewTask,
    ReviewTaskStatus,
    ReviewTaskStep,
    ReviewTaskTriggerType,
    ReviewVersion,
    ReviewVersionDependency,
    ReviewVersionType,
)
from models.diary import AnalysisFeedback, AnalysisRun, Diary, DiaryAnnotation, DiaryAnnotationComment, DiaryEvent, DiaryOrganized
from models.favorite import Favorite
from models.schedule import ScheduleOccurrence
from models.user import User
from schemas.review import (
    ReviewActionUpdate,
    ReviewDetailResponse,
    ReviewEventDocumentUpdate,
    ReviewFeedbackUpsert,
    ReviewListResponse,
    ReviewTaskCreate,
    ReviewTaskListResponse,
    ReviewTaskResponse,
    ReviewDailyDigestResponse,
    ReviewDailyDigestListResponse,
    ReviewVersionResponse,
)
from services.auth import get_current_user
from services.model_runtime import ModelRuntimeError, resolve_model_setting
from services.review_periods import ReviewPeriodError, period_bounds
from services.review_tasks import (
    ReviewTaskError,
    create_first_generation_task,
    create_regeneration_task,
    create_retry_task,
    review_task_manager,
    start_blocking_dependencies,
)


router = APIRouter(tags=["定期回顾"])


def _review(db: Session, review_id: UUID, user: User) -> Review:
    value = db.query(Review).filter(Review.id == review_id, Review.user_id == user.id).first()
    if not value:
        raise HTTPException(status_code=404, detail="回顾不存在")
    return value


def _version(db: Session, version_id: UUID, user: User) -> ReviewVersion:
    value = db.query(ReviewVersion).filter(
        ReviewVersion.id == version_id,
        ReviewVersion.user_id == user.id,
    ).first()
    if not value:
        raise HTTPException(status_code=404, detail="回顾版本不存在")
    return value


def _task_response(task: ReviewTask) -> dict:
    review = task.review
    return {
        "id": task.id,
        "review_id": task.review_id,
        "user_id": task.user_id,
        "review_type": review.review_type,
        "period_start": review.period_start,
        "period_end": review.period_end,
        "trigger_type": task.trigger_type,
        "generation_mode": task.generation_mode,
        "base_version_id": task.base_version_id,
        "retry_of_task_id": task.retry_of_task_id,
        "status": task.status,
        "current_step": task.current_step,
        "freeze_attempts": task.freeze_attempts,
        "event_attempts": task.event_attempts,
        "analysis_attempts": task.analysis_attempts,
        "error_code": task.error_code,
        "error_message": task.error_message,
        "requested_start_at": task.requested_start_at,
        "started_by_user_id": task.started_by_user_id,
        "started_at": task.started_at,
        "completed_at": task.completed_at,
        "result_version_id": task.result_version_id,
        "created_at": task.created_at,
        "updated_at": task.updated_at,
    }


def _detail(db: Session, version: ReviewVersion) -> dict:
    dependency_review_ids = {
        item.dependency_review_id for item in version.dependencies if item.dependency_review_id
    }
    current_by_review = {
        item.id: item.current_version_id
        for item in db.query(Review).filter(Review.id.in_(dependency_review_ids)).all()
    } if dependency_review_ids else {}
    source_updates_available = any(
        item.dependency_review_id
        and item.dependency_version_id
        and current_by_review.get(item.dependency_review_id) != item.dependency_version_id
        for item in version.dependencies
    )
    dependency_version_ids = [
        item.dependency_version_id for item in version.dependencies if item.dependency_version_id
    ]
    if dependency_version_ids and not source_updates_available:
        source_updates_available = bool(
            db.query(ReviewFeedback.id).filter(
                ReviewFeedback.version_id.in_(dependency_version_ids),
                ReviewFeedback.updated_at > version.created_at,
            ).first()
            or db.query(ReviewAction.id).filter(
                ReviewAction.version_id.in_(dependency_version_ids),
                ReviewAction.updated_at > version.created_at,
            ).first()
        )
    if version.review.review_type == "WEEK" and not source_updates_available:
        source_updates_available = _week_sources_changed(db, version)
    return {
        "review": version.review,
        "version": version,
        "feedback": version.feedback,
        "actions": version.actions,
        "action_checks": [
            {
                "id": item.id,
                "version_id": item.version_id,
                "previous_action_id": item.previous_action_id,
                "primary_domain": item.previous_action.primary_domain,
                "previous_action_content": item.previous_action.edited_content or item.previous_action.content,
                "check_status": item.check_status,
                "explanation": item.explanation,
                "evidence_source_ids": item.evidence_source_ids or [],
                "created_at": item.created_at,
            }
            for item in version.action_checks
        ],
        "dependencies": version.dependencies,
        "source_updates_available": source_updates_available,
    }


def _week_sources_changed(db: Session, version: ReviewVersion) -> bool:
    """比较周回顾冻结后的原始来源变化，供详情页提示重新生成。"""
    review = version.review
    frozen_at = version.created_at
    sources = db.query(ReviewSource).join(ReviewSourceSetItem).filter(
        ReviewSourceSetItem.source_set_id == version.source_set_id,
    ).all()
    diary_ids = {
        UUID(str(item.snapshot.get("diary_id")))
        for item in sources
        if item.snapshot.get("diary_id")
    }
    occurrence_ids = {
        UUID(str(item.snapshot.get("occurrence_id")))
        for item in sources
        if item.snapshot.get("occurrence_id")
    }
    if diary_ids:
        current_diaries = {
            item.id: item for item in db.query(Diary).options(joinedload(Diary.organized)).filter(
                Diary.id.in_(diary_ids), Diary.user_id == version.user_id,
            ).all()
        }
        if set(current_diaries) != diary_ids:
            return True
        favorite_diaries = {
            item[0] for item in db.query(Favorite.diary_id).filter(
                Favorite.user_id == version.user_id, Favorite.diary_id.in_(diary_ids),
            ).all()
        }
        event_ids = {
            UUID(str(item.snapshot["event_id"])) for item in sources if item.snapshot.get("event_id")
        }
        favorite_events = {
            item[0] for item in db.query(Favorite.event_id).filter(
                Favorite.user_id == version.user_id, Favorite.event_id.in_(event_ids),
            ).all()
        } if event_ids else set()
        current_events = {
            item.id: item for item in db.query(DiaryEvent).filter(DiaryEvent.id.in_(event_ids)).all()
        } if event_ids else {}
        for source in sources:
            snapshot = source.snapshot or {}
            if not snapshot.get("diary_id"):
                continue
            diary_id = UUID(str(snapshot["diary_id"]))
            diary = current_diaries[diary_id]
            if snapshot.get("content_revision") != diary.content_revision:
                return True
            if snapshot.get("structured_revision") is not None and (
                not diary.organized or snapshot.get("structured_revision") != diary.organized.structured_revision
            ):
                return True
            if "is_favorite" in snapshot:
                event_id = UUID(str(snapshot["event_id"])) if snapshot.get("event_id") else None
                current_favorite = diary_id in favorite_diaries or bool(event_id and event_id in favorite_events)
                if bool(snapshot.get("is_favorite")) != current_favorite:
                    return True
            if "effective_importance" in snapshot:
                event_id = UUID(str(snapshot["event_id"])) if snapshot.get("event_id") else None
                event = current_events.get(event_id) if event_id else None
                if not event:
                    return True
                # 每日提炼会为缺失重要性的旧事件补写 LEGACY_BACKFILL；该回填已参与本次生成，
                # 不能反过来把刚生成的周回顾标记为来源过期。
                if snapshot.get("ai_importance") is None and event.importance_origin == "LEGACY_BACKFILL":
                    if (
                        snapshot.get("user_importance") != event.user_importance
                        or snapshot.get("user_importance_reason") != event.user_importance_reason
                    ):
                        return True
                    continue
                current_importance = {
                    "ai_importance": event.ai_importance,
                    "ai_importance_reason": event.ai_importance_reason,
                    "user_importance": event.user_importance,
                    "user_importance_reason": event.user_importance_reason,
                    "importance_origin": event.importance_origin,
                    "effective_importance": event.user_importance or event.ai_importance,
                }
                if any(snapshot.get(key) != value for key, value in current_importance.items()):
                    return True
    if occurrence_ids:
        current_occurrences = {
            item.id: item for item in db.query(ScheduleOccurrence).options(joinedload(ScheduleOccurrence.task)).filter(
                ScheduleOccurrence.id.in_(occurrence_ids), ScheduleOccurrence.user_id == version.user_id,
            ).all()
        }
        if set(current_occurrences) != occurrence_ids:
            return True
        for source in sources:
            snapshot = source.snapshot or {}
            if not snapshot.get("occurrence_id"):
                continue
            occurrence = current_occurrences[UUID(str(snapshot["occurrence_id"]))]
            current_values = {
                "title": occurrence.title,
                "scheduled_date": occurrence.scheduled_date.isoformat(),
                "is_all_day": occurrence.is_all_day,
                "start_time": occurrence.start_time.isoformat() if occurrence.start_time else None,
                "end_time": occurrence.end_time.isoformat() if occurrence.end_time else None,
                "recurrence_type": occurrence.task.recurrence_type if occurrence.task else "NONE",
                "status": occurrence.status,
                "completed_at": occurrence.completed_at.isoformat() if occurrence.completed_at else None,
                "execution_note": occurrence.execution_note,
            }
            if any(snapshot.get(key) != value for key, value in current_values.items()):
                return True
    diary_scope = or_(
        Diary.id.in_(diary_ids) if diary_ids else False,
        and_(Diary.diary_date >= review.period_start, Diary.diary_date <= review.period_end),
    )
    if db.query(Diary.id).filter(
        Diary.user_id == version.user_id,
        diary_scope,
        Diary.updated_at > frozen_at,
    ).first():
        return True
    if db.query(DiaryOrganized.id).join(Diary, Diary.id == DiaryOrganized.diary_id).filter(
        Diary.user_id == version.user_id,
        diary_scope,
        DiaryOrganized.updated_at > frozen_at,
    ).first():
        return True
    if db.query(AnalysisRun.id).join(Diary, Diary.id == AnalysisRun.diary_id).filter(
        Diary.user_id == version.user_id,
        diary_scope,
        AnalysisRun.updated_at > frozen_at,
    ).first():
        return True
    if db.query(AnalysisFeedback.id).join(AnalysisRun).join(Diary).filter(
        Diary.user_id == version.user_id,
        diary_scope,
        AnalysisFeedback.updated_at > frozen_at,
    ).first():
        return True
    if db.query(DiaryAnnotation.id).join(Diary, Diary.id == DiaryAnnotation.diary_id).filter(
        Diary.user_id == version.user_id,
        diary_scope,
        DiaryAnnotation.updated_at > frozen_at,
    ).first():
        return True
    if db.query(DiaryAnnotationComment.id).join(DiaryAnnotation).join(Diary).filter(
        Diary.user_id == version.user_id,
        diary_scope,
        DiaryAnnotationComment.updated_at > frozen_at,
    ).first():
        return True
    if db.query(Favorite.id).filter(
        Favorite.user_id == version.user_id,
        Favorite.created_at > frozen_at,
        or_(Favorite.diary_id.in_(diary_ids), Favorite.event_id.in_([
            UUID(str(item.snapshot["event_id"])) for item in sources if item.snapshot.get("event_id")
        ])),
    ).first():
        return True
    occurrence_scope = or_(
        ScheduleOccurrence.id.in_(occurrence_ids) if occurrence_ids else False,
        and_(
            ScheduleOccurrence.scheduled_date >= review.period_start,
            ScheduleOccurrence.scheduled_date <= review.period_end,
        ),
    )
    return bool(db.query(ScheduleOccurrence.id).filter(
        ScheduleOccurrence.user_id == version.user_id,
        occurrence_scope,
        ScheduleOccurrence.updated_at > frozen_at,
    ).first())


def _cursor_encode(value: datetime, item_id: UUID) -> str:
    return base64.urlsafe_b64encode(f"{value.isoformat()}|{item_id}".encode()).decode()


def _cursor_decode(value: str | None) -> tuple[datetime, UUID] | None:
    if not value:
        return None
    try:
        raw = base64.urlsafe_b64decode(value.encode()).decode()
        created, item_id = raw.split("|", 1)
        return datetime.fromisoformat(created), UUID(item_id)
    except (ValueError, UnicodeDecodeError):
        raise HTTPException(status_code=400, detail="分页游标无效")


@router.get("/api/reviews", response_model=ReviewListResponse)
def list_reviews(
    review_type: str | None = Query(default=None, alias="type"),
    limit: int = Query(default=30, ge=1, le=100),
    cursor: str | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    query = db.query(Review).filter(Review.user_id == user.id, Review.current_version_id.isnot(None))
    if review_type:
        if review_type.upper() not in {"WEEK", "MONTH"}:
            return {"items": [], "next_cursor": None}
        query = query.filter(Review.review_type == review_type.upper())
    rank = case(
        (Review.review_type == "YEAR", 4),
        (Review.review_type == "QUARTER", 3),
        (Review.review_type == "MONTH", 2),
        else_=1,
    )
    if cursor:
        try:
            raw = base64.urlsafe_b64decode(cursor.encode()).decode()
            end_text, rank_text, id_text = raw.split("|", 2)
            cursor_end = datetime.fromisoformat(end_text).date()
            cursor_rank = int(rank_text)
            cursor_id = UUID(id_text)
        except (ValueError, UnicodeDecodeError):
            raise HTTPException(status_code=400, detail="分页游标无效")
        query = query.filter(or_(
            Review.period_end < cursor_end,
            and_(Review.period_end == cursor_end, rank < cursor_rank),
            and_(Review.period_end == cursor_end, rank == cursor_rank, Review.id < cursor_id),
        ))
    query = query.order_by(Review.period_end.desc(), rank.desc(), Review.id.desc())
    rows = query.limit(limit + 1).all()
    has_more = len(rows) > limit
    rows = rows[:limit]
    items = []
    for item in rows:
        version = item.current_version
        items.append({
            "id": item.id,
            "review_type": item.review_type,
            "period_start": item.period_start,
            "period_end": item.period_end,
            "current_version_id": item.current_version_id,
            "current_version_no": version.version_no if version else None,
            "version_count": len(item.versions),
            "summary": version.summary if version else "",
            "is_unread": item.is_unread,
            "analysis_stale": version.analysis_stale if version else False,
            "updated_at": item.updated_at,
        })
    if not has_more or not rows:
        next_cursor = None
    else:
        last = rows[-1]
        last_rank = {"YEAR": 4, "QUARTER": 3, "MONTH": 2}.get(last.review_type, 1)
        next_cursor = base64.urlsafe_b64encode(
            f"{last.period_end.isoformat()}|{last_rank}|{last.id}".encode()
        ).decode()
    return {"items": items, "next_cursor": next_cursor}


@router.get("/api/reviews-unread-status")
def review_unread_status(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return {
        "has_unread": db.query(Review.id).filter(
            Review.user_id == user.id,
            Review.is_unread.is_(True),
            Review.current_version_id.isnot(None),
        ).first() is not None,
    }


@router.get("/api/reviews/{review_id}", response_model=ReviewDetailResponse)
def get_review(review_id: UUID, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    review = _review(db, review_id, user)
    if not review.current_version_id:
        raise HTTPException(status_code=404, detail="回顾尚未生成完成")
    review.is_unread = False
    db.commit()
    return _detail(db, review.current_version)


@router.get("/api/reviews/{review_id}/versions", response_model=list[ReviewVersionResponse])
def list_versions(review_id: UUID, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    review = _review(db, review_id, user)
    return db.query(ReviewVersion).filter(ReviewVersion.review_id == review.id).order_by(ReviewVersion.version_no.desc()).all()


@router.get("/api/reviews/{review_id}/versions/{version_id}", response_model=ReviewDetailResponse)
def get_review_version(review_id: UUID, version_id: UUID, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    review = _review(db, review_id, user)
    version = _version(db, version_id, user)
    if version.review_id != review.id:
        raise HTTPException(status_code=404, detail="回顾版本不存在")
    return _detail(db, version)


@router.post("/api/reviews/{review_id}/regenerate")
def regenerate_review(review_id: UUID, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    review = _review(db, review_id, user)
    if not review.current_version_id:
        raise HTTPException(status_code=400, detail="回顾尚未生成，应该从任务中心首次生成")
    try:
        resolve_model_setting("review")
    except ModelRuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    task = create_regeneration_task(
        db,
        review,
        base_version_id=review.current_version_id,
        generation_mode=ReviewGenerationMode.FULL.value,
    )
    review_task_manager.wake()
    return _task_response(task)


@router.post("/api/review-versions/{version_id}/regenerate-analysis")
def regenerate_analysis(version_id: UUID, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    version = _version(db, version_id, user)
    if not version.analysis_stale:
        raise HTTPException(status_code=400, detail="当前版本没有待更新的分析")
    try:
        resolve_model_setting("review")
    except ModelRuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    task = create_regeneration_task(
        db,
        version.review,
        base_version_id=version.id,
        generation_mode=ReviewGenerationMode.ANALYSIS_ONLY.value,
    )
    review_task_manager.wake()
    return _task_response(task)


@router.patch("/api/review-versions/{version_id}/event-document")
def edit_event_document(
    version_id: UUID,
    data: ReviewEventDocumentUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    base = _version(db, version_id, user)
    review = db.query(Review).filter(
        Review.id == base.review_id,
        Review.user_id == user.id,
    ).with_for_update().one()
    if review.current_version_id != base.id:
        raise HTTPException(status_code=409, detail="请基于当前版本编辑")
    document = copy.deepcopy(base.event_document or {})
    source_rows = db.query(ReviewSource).join(ReviewSourceSetItem).filter(
        ReviewSourceSetItem.source_set_id == base.source_set_id
    ).all()
    source_by_id = {str(item.id): item for item in source_rows}
    source_id_map = {source_id: source_id for source_id in source_by_id}
    new_set = ReviewSourceSet(
        user_id=user.id,
        status=ReviewSourceSetStatus.BUILDING.value,
        input_snapshot=copy.deepcopy(base.source_set.input_snapshot or {}),
    )
    db.add(new_set)
    db.flush()
    # 冻结来源本身不可变；事件编辑只复用原有关联并追加用户修正来源。
    # 不复制来源行，避免连续编辑时产生悬空的修正来源 ID。
    for source in source_rows:
        db.add(ReviewSourceSetItem(source_set_id=new_set.id, source_id=source.id))
    source_by_new_id = source_by_id

    # 事件文档中的来源 ID 必须指向新版本冻结来源，不能继续引用旧来源集。
    for domain in document.get("domains", []):
        for focus in domain.get("core_focus", []):
            focus["source_ids"] = [source_id_map.get(str(item), str(item)) for item in focus.get("source_ids", [])]
        for thread in domain.get("event_threads", []):
            if thread.get("narrative_correction_source_id"):
                thread["narrative_correction_source_id"] = source_id_map.get(
                    str(thread["narrative_correction_source_id"]),
                    str(thread["narrative_correction_source_id"]),
                )
            thread["prior_context_source_ids"] = [
                source_id_map.get(str(item), str(item)) for item in thread.get("prior_context_source_ids", [])
            ]
            for node in thread.get("nodes", []):
                node["source_ids"] = [source_id_map.get(str(item), str(item)) for item in node.get("source_ids", [])]
            for link in thread.get("links", []):
                link["basis_source_ids"] = [
                    source_id_map.get(str(item), str(item)) for item in link.get("basis_source_ids", [])
                ]
    changed_any = False
    for edit in data.threads:
        target = None
        for domain in document.get("domains", []):
            for thread in domain.get("event_threads", []):
                if str(thread.get("thread_id") or thread.get("thread_key")) == edit.thread_id:
                    target = thread
                    break
            if target:
                break
        if not target:
            raise HTTPException(status_code=404, detail="事件发展主线不存在")
        old_narrative = target.get("narrative") or ""
        if old_narrative == edit.narrative:
            continue
        changed_any = True
        source_date = review.period_start
        source_ids_for_thread = set(target.get("prior_context_source_ids") or [])
        for node in target.get("nodes") or []:
            source_ids_for_thread.update(node.get("source_ids") or [])
        for source_id in source_ids_for_thread:
            source = source_by_new_id.get(str(source_id))
            if source and source.period_role == ReviewPeriodRole.CURRENT.value:
                source_date = source.source_date
                break
        correction = ReviewSource(
            user_id=user.id,
            root_fact_id=f"review-correction:{uuid4()}",
            source_type="USER_FACT_CORRECTION",
            root_source_type="USER_FACT_CORRECTION",
            fact_kind="USER_CORRECTION",
            source_date=source_date,
            period_role="CURRENT",
            relative_position=None,
            content=edit.narrative,
            lineage=[{"review_id": str(review.id), "review_version_id": str(base.id), "content_item_id": edit.thread_id}],
            snapshot={"original_narrative": old_narrative, "corrected_narrative": edit.narrative},
        )
        db.add(correction)
        db.flush()
        db.add(ReviewSourceSetItem(source_set_id=new_set.id, source_id=correction.id))
        target["narrative"] = edit.narrative
        target["user_overridden"] = True
        target["narrative_correction_source_id"] = str(correction.id)
    if not changed_any:
        raise HTTPException(status_code=400, detail="事件内容没有变化")
    new_set.status = ReviewSourceSetStatus.READY.value
    from sqlalchemy import func
    next_no = (db.query(func.max(ReviewVersion.version_no)).filter(ReviewVersion.review_id == review.id).scalar() or 0) + 1
    version = ReviewVersion(
        review_id=review.id,
        user_id=user.id,
        version_no=next_no,
        version_type=ReviewVersionType.EVENT_EDITED.value,
        base_version_id=base.id,
        source_set_id=new_set.id,
        event_document=document,
        analysis_document=copy.deepcopy(base.analysis_document or {}),
        summary=base.summary,
        analysis_stale=True,
        missing_periods=copy.deepcopy(base.missing_periods or []),
        event_model_info=copy.deepcopy(base.event_model_info),
        analysis_model_info=copy.deepcopy(base.analysis_model_info),
    )
    db.add(version)
    db.flush()
    for feedback in base.feedback:
        db.add(ReviewFeedback(
            version_id=version.id,
            user_id=user.id,
            analysis_item_id=feedback.analysis_item_id,
            angle_code=feedback.angle_code,
            rating=feedback.rating,
            comment=feedback.comment,
            is_inherited=True,
            source_feedback_id=feedback.id,
        ))
    for action in base.actions:
        db.add(ReviewAction(
            version_id=version.id,
            user_id=user.id,
            primary_domain=action.primary_domain,
            related_domains=action.related_domains or [],
            content=action.content,
            edited_content=action.edited_content,
            rationale=action.rationale,
            status=action.status,
            source_action_id=action.id,
            is_inherited=True,
            basis_analysis_ids=action.basis_analysis_ids or [],
            basis_source_ids=action.basis_source_ids or [],
            verification_rule=action.verification_rule or {},
        ))
    for dependency in base.dependencies:
        db.add(ReviewVersionDependency(
            version_id=version.id,
            dependency_type=dependency.dependency_type,
            dependency_review_id=dependency.dependency_review_id,
            dependency_version_id=dependency.dependency_version_id,
            period_start=dependency.period_start,
            period_end=dependency.period_end,
            status=dependency.status,
            context_only=dependency.context_only,
        ))
    review.current_version_id = version.id
    review.is_unread = False
    db.commit()
    db.refresh(version)
    return {"version_id": version.id, "analysis_stale": True}


@router.put("/api/review-versions/{version_id}/feedback/{analysis_item_id}")
def upsert_feedback(
    version_id: UUID,
    analysis_item_id: UUID,
    data: ReviewFeedbackUpsert,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    version = _version(db, version_id, user)
    if data.rating is not None and data.rating <= 3 and not data.comment:
        raise HTTPException(status_code=400, detail="1～3 星需要填写文字反馈")
    ids = {
        str(item.get("analysis_item_id"))
        for domain in (version.analysis_document or {}).get("domains", [])
        for item in domain.get("analysis_items", [])
    }
    if str(analysis_item_id) not in ids:
        raise HTTPException(status_code=404, detail="分析项不存在")
    item = db.query(ReviewFeedback).filter(
        ReviewFeedback.version_id == version.id,
        ReviewFeedback.analysis_item_id == analysis_item_id,
    ).first()
    if not item:
        angle_code = "BEHAVIOR_EXECUTION"
        for domain in (version.analysis_document or {}).get("domains", []):
            for candidate in domain.get("analysis_items", []):
                if str(candidate.get("analysis_item_id")) == str(analysis_item_id):
                    angle_code = candidate.get("angle_code") or angle_code
                    break
        item = ReviewFeedback(
            version_id=version.id,
            user_id=user.id,
            analysis_item_id=analysis_item_id,
            angle_code=angle_code,
        )
        db.add(item)
    item.rating = data.rating
    item.comment = data.comment
    item.is_inherited = False
    db.commit()
    db.refresh(item)
    return item


@router.patch("/api/review-versions/{version_id}/actions/{action_id}")
def update_action(
    version_id: UUID,
    action_id: UUID,
    data: ReviewActionUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    version = _version(db, version_id, user)
    action = db.query(ReviewAction).filter(
        ReviewAction.id == action_id,
        ReviewAction.version_id == version.id,
        ReviewAction.user_id == user.id,
    ).first()
    if not action:
        raise HTTPException(status_code=404, detail="行动不存在")
    if data.status is not None:
        action.status = data.status
    if data.edited_content is not None:
        action.edited_content = data.edited_content
    db.commit()
    db.refresh(action)
    return action


@router.get("/api/review-versions/{version_id}/sources/{source_id}")
def get_source(version_id: UUID, source_id: UUID, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    version = _version(db, version_id, user)
    source = db.query(ReviewSource).join(ReviewSourceSetItem).filter(
        ReviewSource.id == source_id,
        ReviewSourceSetItem.source_set_id == version.source_set_id,
        ReviewSource.user_id == user.id,
    ).first()
    if not source:
        raise HTTPException(status_code=404, detail="来源不存在")
    snapshot = source.snapshot or {}
    origin = None
    if snapshot.get("diary_id"):
        origin = {"type": "DIARY", "diary_id": snapshot.get("diary_id"), "id": snapshot.get("event_id")}
    elif snapshot.get("occurrence_id"):
        origin = {"type": "SCHEDULE", "id": snapshot.get("occurrence_id"), "date": source.source_date.isoformat()}
    return {
        "id": source.id,
        "root_fact_id": source.root_fact_id,
        "source_type": source.source_type,
        "root_source_type": source.root_source_type,
        "fact_kind": source.fact_kind,
        "source_date": source.source_date,
        "period_role": source.period_role,
        "relative_position": source.relative_position,
        "origin_review_id": source.origin_review_id,
        "origin_review_version_id": source.origin_review_version_id,
        "origin_content_item_type": source.origin_content_item_type,
        "origin_content_item_id": source.origin_content_item_id,
        "origin_content_item_key": source.origin_content_item_key,
        "lineage": source.lineage or [],
        "content": source.content,
        "snapshot": snapshot,
        "origin": origin,
        "created_at": source.created_at,
    }


@router.post("/api/reviews/{review_id}/read")
def mark_read(review_id: UUID, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    review = _review(db, review_id, user)
    review.is_unread = False
    db.commit()
    return {"ok": True}


@router.get("/api/review-tasks", response_model=ReviewTaskListResponse)
def list_tasks(
    status_filter: str | None = Query(default=None, alias="status"),
    limit: int = Query(default=30, ge=1, le=100),
    cursor: str | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    query = db.query(ReviewTask).filter(ReviewTask.user_id == user.id)
    if status_filter:
        query = query.filter(ReviewTask.status == status_filter.upper())
    decoded = _cursor_decode(cursor)
    if decoded:
        created_at, task_id = decoded
        query = query.filter(or_(
            ReviewTask.created_at < created_at,
            and_(ReviewTask.created_at == created_at, ReviewTask.id < task_id),
        ))
    rows = query.order_by(ReviewTask.created_at.desc(), ReviewTask.id.desc()).limit(limit + 1).all()
    has_more = len(rows) > limit
    rows = rows[:limit]
    next_cursor = _cursor_encode(rows[-1].created_at, rows[-1].id) if has_more and rows else None
    return {"items": [_task_response(item) for item in rows], "next_cursor": next_cursor}


@router.post("/api/review-tasks", response_model=ReviewTaskResponse, status_code=status.HTTP_201_CREATED)
def create_task(
    data: ReviewTaskCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    try:
        period = period_bounds(data.review_type, data.period_start)
        task = create_first_generation_task(db, user.id, period)
    except (ReviewTaskError, ReviewPeriodError, ModelRuntimeError) as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return _task_response(task)


@router.post("/api/review-tasks/{task_id}/start", response_model=ReviewTaskResponse)
def start_task(task_id: UUID, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    task = db.query(ReviewTask).filter(ReviewTask.id == task_id, ReviewTask.user_id == user.id).with_for_update().first()
    if not task:
        raise HTTPException(status_code=404, detail="回顾任务不存在")
    if task.status != ReviewTaskStatus.PENDING_START.value:
        raise HTTPException(status_code=409, detail="当前任务不能启动")
    review = task.review
    period = period_bounds(review.review_type, review.period_start)
    blockers = start_blocking_dependencies(db, user.id, period)
    if blockers:
        raise HTTPException(status_code=409, detail="请先完成：" + "；".join(blockers))
    try:
        resolve_model_setting("review")
    except ModelRuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    task.status = ReviewTaskStatus.QUEUED.value
    task.requested_start_at = datetime.utcnow()
    task.started_by_user_id = user.id
    task.available_at = datetime.utcnow()
    db.commit()
    db.refresh(task)
    review_task_manager.wake()
    return _task_response(task)


@router.get("/api/review-tasks/{task_id}", response_model=ReviewTaskResponse)
def get_task(task_id: UUID, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    task = db.query(ReviewTask).filter(ReviewTask.id == task_id, ReviewTask.user_id == user.id).first()
    if not task:
        raise HTTPException(status_code=404, detail="回顾任务不存在")
    return _task_response(task)


@router.get("/api/daily-digests", response_model=ReviewDailyDigestListResponse)
def list_current_daily_digests(
    limit: int = Query(default=10, ge=1, le=50),
    cursor: str | None = Query(default=None),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """按日期倒序返回当前回顾版本中已有的每日凝练。"""
    query = (
        db.query(ReviewDailyDigest)
        .join(ReviewVersion, ReviewVersion.id == ReviewDailyDigest.review_version_id)
        .join(Review, Review.id == ReviewVersion.review_id)
        .filter(
            Review.user_id == user.id,
            Review.current_version_id == ReviewVersion.id,
            ReviewDailyDigest.status == "READY",
        )
    )
    if cursor:
        try:
            raw = base64.urlsafe_b64decode(cursor.encode()).decode()
            date_text = raw
            cursor_date = datetime.fromisoformat(date_text).date()
        except (ValueError, UnicodeDecodeError):
            raise HTTPException(status_code=400, detail="分页游标无效")
        query = query.filter(ReviewDailyDigest.digest_date < cursor_date)
    rows = query.order_by(
        ReviewDailyDigest.digest_date.desc(), ReviewVersion.created_at.desc(), ReviewVersion.id.desc(),
    ).distinct(ReviewDailyDigest.digest_date).limit(limit + 1).all()
    has_more = len(rows) > limit
    rows = rows[:limit]
    next_cursor = None
    if has_more and rows:
        last = rows[-1]
        next_cursor = base64.urlsafe_b64encode(
            last.digest_date.isoformat().encode()
        ).decode()
    return {"items": rows, "next_cursor": next_cursor}


@router.get("/api/daily-digests/{digest_id}", response_model=ReviewDailyDigestResponse)
def get_current_daily_digest(digest_id: UUID, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    digest = (
        db.query(ReviewDailyDigest)
        .join(ReviewVersion, ReviewVersion.id == ReviewDailyDigest.review_version_id)
        .join(Review, Review.id == ReviewVersion.review_id)
        .filter(
            ReviewDailyDigest.id == digest_id,
            Review.user_id == user.id,
            Review.current_version_id == ReviewVersion.id,
            ReviewDailyDigest.status == "READY",
        )
        .first()
    )
    if not digest:
        raise HTTPException(status_code=404, detail="每日凝练不存在")
    return digest


@router.post("/api/review-tasks/{task_id}/retry", response_model=ReviewTaskResponse)
async def retry_task(task_id: UUID, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    task = db.query(ReviewTask).filter(ReviewTask.id == task_id, ReviewTask.user_id == user.id).first()
    if not task:
        raise HTTPException(status_code=404, detail="回顾任务不存在")
    try:
        resolve_model_setting("review")
        retry = create_retry_task(db, task)
    except (ReviewTaskError, ModelRuntimeError) as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    retry.status = ReviewTaskStatus.RUNNING.value
    retry.run_token = uuid4()
    retry.started_at = retry.started_at or datetime.utcnow()
    retry.lease_until = datetime.utcnow() + timedelta(minutes=10)
    db.commit()
    db.refresh(retry)
    review_task_manager.start_claimed_task(retry.id, retry.run_token)
    return _task_response(retry)
