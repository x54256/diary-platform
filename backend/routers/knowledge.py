"""知识沉淀任务与知识事件 API。"""

import base64
import json
from datetime import date, datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import and_, func, or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from database import get_db
from models.diary import Diary, DiaryEvent, DiaryOrganized, DiaryStatus, OrganizeTask
from models.knowledge import KnowledgeAtomicEvent, KnowledgeDeposit, KnowledgeMatter, KnowledgeTask
from models.user import User
from schemas.knowledge import (
    DiaryKnowledgeStatusResponse, KnowledgeEventDetail, KnowledgeEventListItem,
    KnowledgeEventListResponse, KnowledgeMatterDetail, KnowledgeMatterEventItem,
    KnowledgeMatterListItem, KnowledgeMatterListResponse, KnowledgeMatterRef,
    KnowledgeMatterUpgradeRequest, KnowledgeTaskResponse, KnowledgeUpgradePendingDiary,
    KnowledgeUpgradeStatusResponse,
)
from services.auth import get_current_user
from services.knowledge_tasks import knowledge_task_manager
from services.model_management import get_embedding_config
from services.model_runtime import ModelRuntimeError, resolve_model_setting
from services.pipeline import cleanup_checkpoint
from services.task_environment import TASK_ENVIRONMENT

router = APIRouter(prefix="/api", tags=["知识库"])


def _error(code: str, message: str, http_status: int = 409) -> HTTPException:
    return HTTPException(status_code=http_status, detail={"code": code, "message": message})


def _task_response(task: KnowledgeTask) -> KnowledgeTaskResponse:
    return KnowledgeTaskResponse.model_validate(task)


def _model_configured() -> bool:
    try:
        resolve_model_setting("knowledge", "knowledge_event_extract")
        resolve_model_setting("knowledge", "knowledge_event_review")
        resolve_model_setting("knowledge", "knowledge_matter_assign")
        resolve_model_setting("knowledge", "knowledge_matter_overview")
        get_embedding_config()
        return True
    except ModelRuntimeError:
        return False


def _source(db: Session, diary: Diary) -> DiaryOrganized:
    if diary.status != DiaryStatus.analyzed:
        raise _error("DIARY_NOT_ANALYZED", "日记完成分析后才能沉淀知识", 400)
    organized = db.query(DiaryOrganized).filter(DiaryOrganized.diary_id == diary.id).first()
    if not organized:
        raise _error("STRUCTURED_SOURCE_MISSING", "当前日记没有结构化内容", 400)
    events = db.query(DiaryEvent).filter(DiaryEvent.diary_organized_id == organized.id).order_by(DiaryEvent.sort_order, DiaryEvent.id).all()
    if not events:
        raise _error("EMPTY_STRUCTURED_DIARY", "结构化日记没有事件", 400)
    def content_empty(value) -> bool:
        if value is None or value == []:
            return True
        if isinstance(value, str):
            if not value.strip():
                return True
            try:
                parsed = json.loads(value)
                return isinstance(parsed, list) and not parsed
            except (TypeError, json.JSONDecodeError):
                return False
        return False
    for index, event in enumerate(events, start=1):
        values = (event.event_title, event.body)
        if all(content_empty(value) for value in values):
            raise _error("EMPTY_STRUCTURED_EVENT", f"第 {index} 个结构化事件为空", 400)
    return organized


@router.get("/diaries/{diary_id}/knowledge-status", response_model=DiaryKnowledgeStatusResponse)
def diary_knowledge_status(
    diary_id: UUID, db: Session = Depends(get_db), current_user: User = Depends(get_current_user),
):
    diary = db.query(Diary).filter(Diary.id == diary_id, Diary.user_id == current_user.id, Diary.deleted_at.is_(None)).first()
    if not diary:
        raise HTTPException(status_code=404, detail="日记不存在")
    configured = _model_configured()
    source_busy = db.query(OrganizeTask.id).filter(
        OrganizeTask.diary_id == diary.id, OrganizeTask.status == "running",
    ).first() is not None
    source_ready = False
    source_reason = None
    if diary.status != DiaryStatus.analyzed:
        source_reason = "日记完成分析后才能沉淀知识。"
    elif source_busy:
        source_reason = "日记正在整理或分析，请等待任务完成。"
    else:
        try:
            _source(db, diary)
            source_ready = True
        except HTTPException as exc:
            detail = exc.detail
            source_reason = detail.get("message") if isinstance(detail, dict) else str(detail)
    deposit = db.query(KnowledgeDeposit).filter(KnowledgeDeposit.diary_id == diary.id, KnowledgeDeposit.user_id == current_user.id).first()
    if deposit:
        count = db.query(func.count(KnowledgeAtomicEvent.id)).filter(KnowledgeAtomicEvent.diary_id == diary.id).scalar() or 0
        return {"state": "DEPOSITED", "model_configured": configured, "available": True, "atomic_event_count": count}
    active = db.query(KnowledgeTask).filter(
        KnowledgeTask.environment == TASK_ENVIRONMENT,
        KnowledgeTask.user_id == current_user.id, KnowledgeTask.status.in_(("QUEUED", "RUNNING")),
    ).order_by(KnowledgeTask.created_at.desc()).first()
    unavailable_reason = None
    if not configured:
        unavailable_reason = "管理员尚未配置知识沉淀模型。"
    elif active is not None or source_busy:
        unavailable_reason = "已有整理、分析或知识任务正在执行，请等待任务完成。"
    elif not source_ready:
        unavailable_reason = source_reason
    if active and active.diary_id == diary.id:
        return {"state": "PROCESSING", "model_configured": configured, "available": True, "task": _task_response(active)}
    failed = None
    if diary.organized:
        failed = db.query(KnowledgeTask).filter(
            KnowledgeTask.environment == TASK_ENVIRONMENT,
            KnowledgeTask.diary_id == diary.id, KnowledgeTask.user_id == current_user.id,
            KnowledgeTask.source_structured_revision == diary.organized.structured_revision,
            KnowledgeTask.status == "FAILED",
        ).order_by(KnowledgeTask.updated_at.desc()).first()
    if failed:
        return {
            "state": "FAILED", "model_configured": configured,
            "available": configured and active is None and source_ready,
            "blocked_by_other_task": active is not None or source_busy,
            "unavailable_reason": unavailable_reason, "task": _task_response(failed),
        }
    available = configured and source_ready and active is None
    return {
        "state": "NOT_DEPOSITED", "model_configured": configured, "available": available,
        "blocked_by_other_task": active is not None or source_busy,
        "unavailable_reason": unavailable_reason,
    }


@router.post("/diaries/{diary_id}/knowledge-deposit", response_model=KnowledgeTaskResponse, status_code=status.HTTP_202_ACCEPTED)
def create_knowledge_deposit(
    diary_id: UUID, db: Session = Depends(get_db), current_user: User = Depends(get_current_user),
):
    diary = db.query(Diary).filter(
        Diary.id == diary_id, Diary.user_id == current_user.id, Diary.deleted_at.is_(None),
    ).with_for_update().first()
    if not diary:
        raise HTTPException(status_code=404, detail="日记不存在")
    if db.query(KnowledgeDeposit.diary_id).filter(KnowledgeDeposit.diary_id == diary.id).first():
        raise _error("ALREADY_DEPOSITED", "该日记已完成知识沉淀")
    same_active = db.query(KnowledgeTask).filter(
        KnowledgeTask.environment == TASK_ENVIRONMENT,
        KnowledgeTask.diary_id == diary.id, KnowledgeTask.user_id == current_user.id,
        KnowledgeTask.status.in_(("QUEUED", "RUNNING")),
    ).first()
    if same_active:
        return _task_response(same_active)
    if db.query(OrganizeTask.id).filter(OrganizeTask.diary_id == diary.id, OrganizeTask.status == "running").first():
        raise _error("SOURCE_BUSY", "日记正在整理或分析，请等待任务完成")
    other_active = db.query(KnowledgeTask.id).filter(
        KnowledgeTask.environment == TASK_ENVIRONMENT,
        KnowledgeTask.user_id == current_user.id, KnowledgeTask.status.in_(("QUEUED", "RUNNING")),
    ).first()
    if other_active:
        raise _error("ACTIVE_TASK_EXISTS", "当前已有其他知识沉淀任务")
    try:
        resolve_model_setting("knowledge", "knowledge_event_extract")
        resolve_model_setting("knowledge", "knowledge_event_review")
        resolve_model_setting("knowledge", "knowledge_matter_assign")
        resolve_model_setting("knowledge", "knowledge_matter_overview")
    except ModelRuntimeError as exc:
        raise _error("KNOWLEDGE_MODEL_NOT_CONFIGURED", str(exc), 400) from exc
    try:
        get_embedding_config()
    except ModelRuntimeError as exc:
        raise _error("EMBEDDING_MODEL_NOT_CONFIGURED", "管理员尚未配置向量模型，请先完成配置", 400) from exc
    organized = _source(db, diary)
    task = KnowledgeTask(
        user_id=current_user.id, diary_id=diary.id, source_diary_organized_id=organized.id,
        source_structured_revision=organized.structured_revision,
        status="QUEUED", available_at=datetime.utcnow(),
    )
    db.add(task)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        existing = db.query(KnowledgeTask).filter(
            KnowledgeTask.environment == TASK_ENVIRONMENT,
            KnowledgeTask.user_id == current_user.id, KnowledgeTask.status.in_(("QUEUED", "RUNNING")),
        ).first()
        if existing and existing.diary_id == diary.id:
            return _task_response(existing)
        raise _error("ACTIVE_TASK_EXISTS", "当前已有其他知识沉淀任务") from exc
    db.refresh(task)
    knowledge_task_manager.wake()
    return _task_response(task)


@router.get("/knowledge-tasks/{task_id}", response_model=KnowledgeTaskResponse)
def get_knowledge_task(task_id: UUID, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    task = db.query(KnowledgeTask).filter(
        KnowledgeTask.id == task_id, KnowledgeTask.environment == TASK_ENVIRONMENT,
        KnowledgeTask.user_id == current_user.id,
    ).first()
    if not task:
        raise HTTPException(status_code=404, detail="知识任务不存在")
    return _task_response(task)


@router.post("/knowledge-tasks/{task_id}/retry", response_model=KnowledgeTaskResponse, status_code=status.HTTP_202_ACCEPTED)
async def retry_knowledge_task(
    task_id: UUID, db: Session = Depends(get_db), current_user: User = Depends(get_current_user),
):
    task = db.query(KnowledgeTask).filter(
        KnowledgeTask.id == task_id, KnowledgeTask.environment == TASK_ENVIRONMENT,
        KnowledgeTask.user_id == current_user.id,
    ).with_for_update().first()
    if not task:
        raise HTTPException(status_code=404, detail="知识任务不存在")
    if task.status in ("QUEUED", "RUNNING"):
        return _task_response(task)
    if task.status != "FAILED":
        raise _error("TASK_NOT_RETRYABLE", "当前任务不能重试", 400)
    # 事项阶段：PUBLISH 已成功（存在成功记录）的任务失败于事项匹配，首版不提供重试，
    # 避免重跑发布产生重复知识事件。
    if db.query(KnowledgeDeposit.diary_id).filter(KnowledgeDeposit.diary_id == task.diary_id).first():
        raise _error("TASK_NOT_RETRYABLE", "知识事件已发布，事项匹配失败暂不支持重试", 400)
    diary = db.query(Diary).filter(Diary.id == task.diary_id, Diary.user_id == current_user.id, Diary.deleted_at.is_(None)).with_for_update().first()
    if diary and db.query(OrganizeTask.id).filter(
        OrganizeTask.diary_id == diary.id, OrganizeTask.status == "running",
    ).first():
        raise _error("SOURCE_BUSY", "日记正在整理或分析，请等待任务完成")
    changed = not diary or diary.status != DiaryStatus.analyzed
    if not changed:
        try:
            organized = _source(db, diary)
            changed = organized.id != task.source_diary_organized_id or organized.structured_revision != task.source_structured_revision
        except HTTPException:
            changed = True
    if changed:
        task.error_code = "SOURCE_CHANGED"
        task.error_message = "日记来源已变化，请重新发起知识沉淀"
        db.commit()
        try:
            await cleanup_checkpoint(str(task.id))
            task.checkpoint_cleaned_at = datetime.utcnow()
            db.commit()
        except Exception:
            db.rollback()
        raise _error("SOURCE_CHANGED", "日记来源已变化，请重新发起知识沉淀")
    if db.query(KnowledgeTask.id).filter(
        KnowledgeTask.user_id == current_user.id, KnowledgeTask.id != task.id,
        KnowledgeTask.status.in_(("QUEUED", "RUNNING")),
    ).first():
        raise _error("ACTIVE_TASK_EXISTS", "当前已有其他知识沉淀任务")
    try:
        resolve_model_setting("knowledge", "knowledge_event_extract")
        resolve_model_setting("knowledge", "knowledge_event_review")
    except ModelRuntimeError as exc:
        raise _error("KNOWLEDGE_MODEL_NOT_CONFIGURED", str(exc), 400) from exc
    task.status = "QUEUED"
    task.retry_count += 1
    task.available_at = datetime.utcnow()
    task.lease_until = None
    task.run_token = None
    task.error_code = None
    task.error_message = None
    task.completed_at = None
    task.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(task)
    knowledge_task_manager.wake()
    return _task_response(task)


def _encode_cursor(event: KnowledgeAtomicEvent, diary: Diary, source_event: DiaryEvent) -> str:
    raw = json.dumps({
        "diary_date": diary.diary_date.isoformat(), "diary_created": diary.created_at.isoformat(),
        "diary_id": str(diary.id), "source_event_order": source_event.sort_order,
        "source_event_id": str(source_event.id), "source_order": event.source_order, "event_id": str(event.id),
    }, separators=(",", ":")).encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _decode_cursor(value: str) -> tuple[date, datetime, UUID, int, UUID, int, UUID]:
    try:
        data = json.loads(base64.urlsafe_b64decode(value + "=" * (-len(value) % 4)))
        return (
            date.fromisoformat(data["diary_date"]), datetime.fromisoformat(data["diary_created"]), UUID(data["diary_id"]),
            int(data["source_event_order"]), UUID(data["source_event_id"]), int(data["source_order"]), UUID(data["event_id"]),
        )
    except Exception as exc:
        raise _error("INVALID_CURSOR", "分页游标不合法", 400) from exc


@router.get("/knowledge/events", response_model=KnowledgeEventListResponse)
def list_knowledge_events(
    limit: int = Query(20, ge=1, le=50), cursor: str | None = None,
    db: Session = Depends(get_db), current_user: User = Depends(get_current_user),
):
    query = db.query(
        KnowledgeAtomicEvent, Diary, DiaryOrganized.title, DiaryEvent,
    ).join(
        Diary, Diary.id == KnowledgeAtomicEvent.diary_id,
    ).join(
        DiaryOrganized, DiaryOrganized.diary_id == KnowledgeAtomicEvent.diary_id,
    ).join(
        DiaryEvent, DiaryEvent.id == KnowledgeAtomicEvent.source_diary_event_id,
    ).filter(KnowledgeAtomicEvent.user_id == current_user.id)
    if cursor:
        cursor_date, cursor_diary_created, cursor_diary_id, cursor_event_order, cursor_event_id, cursor_source_order, cursor_id = _decode_cursor(cursor)
        query = query.filter(or_(
            Diary.diary_date < cursor_date,
            and_(Diary.diary_date == cursor_date, Diary.created_at < cursor_diary_created),
            and_(Diary.diary_date == cursor_date, Diary.created_at == cursor_diary_created, Diary.id < cursor_diary_id),
            and_(
                Diary.diary_date == cursor_date, Diary.created_at == cursor_diary_created, Diary.id == cursor_diary_id,
                or_(
                    DiaryEvent.sort_order > cursor_event_order,
                    and_(DiaryEvent.sort_order == cursor_event_order, DiaryEvent.id > cursor_event_id),
                    and_(DiaryEvent.sort_order == cursor_event_order, DiaryEvent.id == cursor_event_id, KnowledgeAtomicEvent.source_order > cursor_source_order),
                    and_(DiaryEvent.sort_order == cursor_event_order, DiaryEvent.id == cursor_event_id, KnowledgeAtomicEvent.source_order == cursor_source_order, KnowledgeAtomicEvent.id > cursor_id),
                ),
            ),
        ))
    rows = query.order_by(
        Diary.diary_date.desc(), Diary.created_at.desc(), Diary.id.desc(),
        DiaryEvent.sort_order.asc(), DiaryEvent.id.asc(), KnowledgeAtomicEvent.source_order.asc(), KnowledgeAtomicEvent.id.asc(),
    ).limit(limit + 1).all()
    has_more = len(rows) > limit
    rows = rows[:limit]
    items = [KnowledgeEventListItem(
        id=event.id, diary_id=event.diary_id, source_diary_event_id=source_event.id,
        source_event_order=source_event.sort_order, source_order=event.source_order, title=event.title, content=event.content,
        occurred_on=event.occurred_on, occurred_time=event.occurred_time,
        source_diary_date=diary.diary_date, source_diary_title=diary_title,
        source_event_title=source_event.event_title, created_at=event.created_at,
    ) for event, diary, diary_title, source_event in rows]
    return {"items": items, "next_cursor": _encode_cursor(rows[-1][0], rows[-1][1], rows[-1][3]) if has_more and rows else None}


@router.get("/knowledge/events/{event_id}", response_model=KnowledgeEventDetail)
def get_knowledge_event(
    event_id: UUID, db: Session = Depends(get_db), current_user: User = Depends(get_current_user),
):
    row = db.query(
        KnowledgeAtomicEvent, DiaryOrganized.title, DiaryOrganized.summary,
        Diary.diary_date, DiaryEvent,
    ).join(
        Diary, Diary.id == KnowledgeAtomicEvent.diary_id,
    ).join(
        DiaryOrganized, DiaryOrganized.diary_id == KnowledgeAtomicEvent.diary_id,
    ).join(
        DiaryEvent, DiaryEvent.id == KnowledgeAtomicEvent.source_diary_event_id,
    ).filter(KnowledgeAtomicEvent.id == event_id, KnowledgeAtomicEvent.user_id == current_user.id).first()
    if not row:
        raise HTTPException(status_code=404, detail="知识事件不存在")
    event, diary_title, diary_summary, diary_date, source_event = row
    matter_ref = None
    if event.matter_id:
        matter = db.query(KnowledgeMatter).filter(
            KnowledgeMatter.id == event.matter_id, KnowledgeMatter.user_id == current_user.id,
        ).first()
        if matter:
            matter_ref = KnowledgeMatterRef(id=matter.id, name=matter.name)
    return KnowledgeEventDetail(
        id=event.id, diary_id=event.diary_id, source_diary_event_id=event.source_diary_event_id,
        source_event_order=source_event.sort_order, source_order=event.source_order, title=event.title, content=event.content,
        occurred_on=event.occurred_on, occurred_time=event.occurred_time, source_diary_date=diary_date,
        source_diary_title=diary_title, source_event_title=source_event.event_title,
        source_diary_summary=diary_summary, created_at=event.created_at, matter=matter_ref,
    )


def _encode_matter_cursor(matter: KnowledgeMatter) -> str:
    raw = json.dumps({
        "last_event_on": matter.last_event_on.isoformat(),
        "updated_at": matter.updated_at.isoformat(),
        "id": str(matter.id),
    }, separators=(",", ":")).encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _decode_matter_cursor(value: str) -> tuple[date, datetime, UUID]:
    try:
        data = json.loads(base64.urlsafe_b64decode(value + "=" * (-len(value) % 4)))
        return date.fromisoformat(data["last_event_on"]), datetime.fromisoformat(data["updated_at"]), UUID(data["id"])
    except Exception as exc:
        raise _error("INVALID_CURSOR", "分页游标不合法", 400) from exc


@router.get("/knowledge/matters", response_model=KnowledgeMatterListResponse)
def list_knowledge_matters(
    limit: int = Query(20, ge=1, le=50), cursor: str | None = None,
    db: Session = Depends(get_db), current_user: User = Depends(get_current_user),
):
    query = db.query(KnowledgeMatter).filter(KnowledgeMatter.user_id == current_user.id)
    if cursor:
        cursor_on, cursor_updated, cursor_id = _decode_matter_cursor(cursor)
        query = query.filter(or_(
            KnowledgeMatter.last_event_on < cursor_on,
            and_(KnowledgeMatter.last_event_on == cursor_on, KnowledgeMatter.updated_at < cursor_updated),
            and_(
                KnowledgeMatter.last_event_on == cursor_on,
                KnowledgeMatter.updated_at == cursor_updated,
                KnowledgeMatter.id < cursor_id,
            ),
        ))
    rows = query.order_by(
        KnowledgeMatter.last_event_on.desc(), KnowledgeMatter.updated_at.desc(), KnowledgeMatter.id.desc(),
    ).limit(limit + 1).all()
    has_more = len(rows) > limit
    rows = rows[:limit]
    items = [KnowledgeMatterListItem(
        id=matter.id, name=matter.name, status=matter.status, overview=matter.overview,
        event_count=matter.event_count, last_event_on=matter.last_event_on,
    ) for matter in rows]
    return {"items": items, "next_cursor": _encode_matter_cursor(rows[-1]) if has_more and rows else None}


@router.post("/knowledge/matters/upgrade", response_model=KnowledgeTaskResponse, status_code=status.HTTP_202_ACCEPTED)
def create_matter_upgrade(
    payload: KnowledgeMatterUpgradeRequest,
    db: Session = Depends(get_db), current_user: User = Depends(get_current_user),
):
    """对已完成 ATOMIC_EVENTS 的单篇日记创建事项升级任务（5.4）。"""
    diary = db.query(Diary).filter(
        Diary.id == payload.diary_id, Diary.user_id == current_user.id, Diary.deleted_at.is_(None),
    ).with_for_update().first()
    if not diary:
        raise HTTPException(status_code=404, detail="日记不存在")
    deposit = db.query(KnowledgeDeposit).filter(
        KnowledgeDeposit.diary_id == diary.id, KnowledgeDeposit.user_id == current_user.id,
    ).first()
    if not deposit:
        raise _error("NOT_DEPOSITED", "该日记尚未沉淀知识事件", 400)
    if deposit.completed_stage == "MATTERS":
        raise _error("ALREADY_UPGRADED", "该日记已完成事项整理")
    active = db.query(KnowledgeTask).filter(
        KnowledgeTask.environment == TASK_ENVIRONMENT,
        KnowledgeTask.user_id == current_user.id, KnowledgeTask.status.in_(("QUEUED", "RUNNING")),
    ).order_by(KnowledgeTask.created_at.desc()).first()
    if active:
        if active.task_type == "UPGRADE" and active.diary_id == diary.id:
            return _task_response(active)
        raise _error("ACTIVE_TASK_EXISTS", "当前已有其他知识任务正在执行")
    try:
        resolve_model_setting("knowledge", "knowledge_matter_assign")
        resolve_model_setting("knowledge", "knowledge_matter_overview")
    except ModelRuntimeError as exc:
        raise _error("KNOWLEDGE_MODEL_NOT_CONFIGURED", str(exc), 400) from exc
    try:
        get_embedding_config()
    except ModelRuntimeError as exc:
        raise _error("EMBEDDING_MODEL_NOT_CONFIGURED", "管理员尚未配置向量模型，请先完成配置", 400) from exc
    task = KnowledgeTask(
        user_id=current_user.id, diary_id=diary.id,
        source_diary_organized_id=deposit.source_diary_organized_id,
        source_structured_revision=deposit.source_structured_revision,
        task_type="UPGRADE", status="QUEUED", available_at=datetime.utcnow(),
    )
    db.add(task)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        existing = db.query(KnowledgeTask).filter(
            KnowledgeTask.environment == TASK_ENVIRONMENT,
            KnowledgeTask.user_id == current_user.id, KnowledgeTask.status.in_(("QUEUED", "RUNNING")),
        ).first()
        if existing and existing.task_type == "UPGRADE" and existing.diary_id == diary.id:
            return _task_response(existing)
        raise _error("ACTIVE_TASK_EXISTS", "当前已有其他知识任务正在执行") from exc
    db.refresh(task)
    knowledge_task_manager.wake()
    return _task_response(task)


@router.get("/knowledge/matters/upgrade-status", response_model=KnowledgeUpgradeStatusResponse)
def get_matter_upgrade_status(
    db: Session = Depends(get_db), current_user: User = Depends(get_current_user),
):
    """待升级日记列表与当前活动任务，驱动事件页的"整理事项"入口。"""
    rows = db.query(KnowledgeDeposit, Diary, DiaryOrganized.title).join(
        Diary, Diary.id == KnowledgeDeposit.diary_id,
    ).join(
        DiaryOrganized, DiaryOrganized.id == KnowledgeDeposit.source_diary_organized_id,
    ).filter(
        KnowledgeDeposit.user_id == current_user.id,
        KnowledgeDeposit.completed_stage == "ATOMIC_EVENTS",
        Diary.deleted_at.is_(None),
    ).order_by(KnowledgeDeposit.deposited_at.asc()).all()
    pending = [KnowledgeUpgradePendingDiary(
        diary_id=deposit.diary_id, diary_date=diary.diary_date, diary_title=diary_title,
    ) for deposit, diary, diary_title in rows]
    active = db.query(KnowledgeTask).filter(
        KnowledgeTask.environment == TASK_ENVIRONMENT,
        KnowledgeTask.user_id == current_user.id, KnowledgeTask.status.in_(("QUEUED", "RUNNING")),
    ).order_by(KnowledgeTask.created_at.desc()).first()
    return {
        "pending_diaries": pending,
        "active_task": _task_response(active) if active else None,
    }


@router.get("/knowledge/matters/{matter_id}", response_model=KnowledgeMatterDetail)
def get_knowledge_matter(
    matter_id: UUID, db: Session = Depends(get_db), current_user: User = Depends(get_current_user),
):
    matter = db.query(KnowledgeMatter).filter(
        KnowledgeMatter.id == matter_id, KnowledgeMatter.user_id == current_user.id,
    ).first()
    if not matter:
        raise HTTPException(status_code=404, detail="事项不存在")
    event_rows = db.query(KnowledgeAtomicEvent).filter(
        KnowledgeAtomicEvent.matter_id == matter.id, KnowledgeAtomicEvent.user_id == current_user.id,
    ).order_by(
        KnowledgeAtomicEvent.occurred_on.desc(),
        KnowledgeAtomicEvent.occurred_time.desc().nullslast(),
        KnowledgeAtomicEvent.id.desc(),
    ).all()
    events = [KnowledgeMatterEventItem(
        id=event.id, title=event.title, occurred_on=event.occurred_on, occurred_time=event.occurred_time,
        first_paragraph=(event.content[0] if event.content else ""),
    ) for event in event_rows]
    return KnowledgeMatterDetail(
        id=matter.id, name=matter.name, status=matter.status, overview=matter.overview,
        started_on=matter.started_on, last_event_on=matter.last_event_on,
        event_count=matter.event_count, created_at=matter.created_at, events=events,
    )
