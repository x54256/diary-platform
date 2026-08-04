"""日记详情行动项接口。"""

from datetime import date, datetime, timedelta
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from database import get_db
from models.diary import Diary, DiaryActionItem, DiaryActionScheduleLink, DiaryStatus
from models.schedule import ScheduleOccurrence, ScheduleTask
from models.user import User
from routers.schedules import (
    IMMEDIATE_WINDOW_DAYS,
    cached_holiday_sets,
    ensure_occurrences_for_task,
    enqueue_maintenance_job,
    sunday_weekday,
)
from schemas.actions import (
    DiaryActionCompletion,
    DiaryActionResponse,
    DiaryActionSyncRequest,
    DiaryActionUpdate,
)
from services.action_items import (
    get_owned_action,
    list_actions,
    serialize_action,
    set_action_completion,
    unlink_action_schedule,
    update_action_fields,
)
from services.auth import get_current_user

router = APIRouter(prefix="/api", tags=["日记行动项"])


def _owned_analyzed_diary(diary_id: UUID, db: Session, current_user: User) -> Diary:
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
        raise HTTPException(status_code=404, detail="日记不存在")
    if diary.status != DiaryStatus.analyzed:
        raise HTTPException(status_code=409, detail="日记完成分析后才能使用行动项")
    return diary


def _create_schedule_task(db: Session, user_id, payload, title: str) -> tuple[ScheduleTask, ScheduleOccurrence]:
    if payload.start_date < date.today():
        raise HTTPException(status_code=400, detail="日程开始日期不能早于今天")
    weekdays = payload.weekdays or (
        [sunday_weekday(payload.start_date)] if payload.recurrence_type == "WEEKLY" else []
    )
    month_day = payload.month_day or (
        payload.start_date.day if payload.recurrence_type == "MONTHLY_DATE" else None
    )
    nth_week = payload.nth_week or (
        ((payload.start_date.day - 1) // 7) + 1
        if payload.recurrence_type == "MONTHLY_NTH_WEEKDAY" else None
    )
    nth_weekday = payload.nth_weekday if payload.nth_weekday is not None else (
        sunday_weekday(payload.start_date)
        if payload.recurrence_type == "MONTHLY_NTH_WEEKDAY" else None
    )
    task = ScheduleTask(
        user_id=user_id,
        title=(payload.title or title).strip(),
        is_all_day=payload.is_all_day,
        start_date=payload.start_date,
        start_time=payload.start_time,
        end_time=payload.end_time,
        recurrence_type=payload.recurrence_type,
        interval=str(payload.interval),
        weekdays=",".join(map(str, weekdays)) or None,
        month_day=str(month_day) if month_day else None,
        nth_week=str(nth_week) if nth_week else None,
        nth_weekday=str(nth_weekday) if nth_weekday is not None else None,
        recurrence_month=str(payload.recurrence_month) if payload.recurrence_month else None,
        recurrence_until=payload.recurrence_until,
        recurrence_count=str(payload.recurrence_count) if payload.recurrence_count else None,
    )
    db.add(task)
    db.flush()
    immediate_end = payload.start_date + timedelta(days=IMMEDIATE_WINDOW_DAYS - 1)
    workdays, restdays = cached_holiday_sets(db, task, immediate_end)
    ensure_occurrences_for_task(db, task, immediate_end, workdays, restdays, IMMEDIATE_WINDOW_DAYS)
    if task.recurrence_type != "NONE":
        enqueue_maintenance_job(db, task.id, "ENSURE", immediate_end + timedelta(days=1))
    occurrence = (
        db.query(ScheduleOccurrence)
        .filter(
            ScheduleOccurrence.task_id == task.id,
            ScheduleOccurrence.scheduled_date == payload.start_date,
        )
        .first()
    )
    if not occurrence:
        raise HTTPException(status_code=400, detail="无法生成同步日程实例")
    return task, occurrence


@router.get("/diaries/{diary_id}/actions", response_model=list[DiaryActionResponse])
def get_diary_actions(diary_id: UUID, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    _owned_analyzed_diary(diary_id, db, current_user)
    return list_actions(db, diary_id, current_user.id)


@router.put("/diary-actions/{action_id}", response_model=DiaryActionResponse)
def update_diary_action(
    action_id: UUID,
    data: DiaryActionUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    action = get_owned_action(db, action_id, current_user.id)
    if data.schedule and data.schedule.start_date < date.today() and action.schedule_links:
        raise HTTPException(status_code=400, detail="已同步日程的开始日期不能早于今天")
    link = (
        db.query(DiaryActionScheduleLink)
        .filter(
            DiaryActionScheduleLink.action_item_id == action.id,
            DiaryActionScheduleLink.unlinked_at.is_(None),
        )
        .first()
    )
    update_action_fields(action, data.title, data.schedule)
    if link and link.schedule_task_id:
        task = db.query(ScheduleTask).filter(ScheduleTask.id == link.schedule_task_id).first()
        if task:
            if data.schedule:
                weekdays = data.schedule.weekdays or (
                    [sunday_weekday(data.schedule.start_date)]
                    if data.schedule.recurrence_type == "WEEKLY" else []
                )
                month_day = data.schedule.month_day or (
                    data.schedule.start_date.day
                    if data.schedule.recurrence_type == "MONTHLY_DATE" else None
                )
                nth_week = data.schedule.nth_week or (
                    ((data.schedule.start_date.day - 1) // 7) + 1
                    if data.schedule.recurrence_type == "MONTHLY_NTH_WEEKDAY" else None
                )
                nth_weekday = data.schedule.nth_weekday if data.schedule.nth_weekday is not None else (
                    sunday_weekday(data.schedule.start_date)
                    if data.schedule.recurrence_type == "MONTHLY_NTH_WEEKDAY" else None
                )
                task.title = data.title or action.title
                task.is_all_day = data.schedule.is_all_day
                task.start_date = data.schedule.start_date
                task.start_time = data.schedule.start_time
                task.end_time = data.schedule.end_time
                task.recurrence_type = data.schedule.recurrence_type
                task.interval = str(data.schedule.interval)
                task.weekdays = ",".join(map(str, weekdays)) or None
                task.month_day = str(month_day) if month_day else None
                task.nth_week = str(nth_week) if nth_week else None
                task.nth_weekday = str(nth_weekday) if nth_weekday is not None else None
                task.recurrence_month = str(data.schedule.recurrence_month) if data.schedule.recurrence_month else None
                task.recurrence_until = data.schedule.recurrence_until
                task.recurrence_count = str(data.schedule.recurrence_count) if data.schedule.recurrence_count else None
                db.query(ScheduleOccurrence).filter(
                    ScheduleOccurrence.task_id == task.id,
                    ScheduleOccurrence.scheduled_date >= date.today(),
                    ScheduleOccurrence.status == "pending",
                ).delete(synchronize_session=False)
                immediate_end = max(task.start_date, date.today()) + timedelta(days=IMMEDIATE_WINDOW_DAYS - 1)
                workdays, restdays = cached_holiday_sets(db, task, immediate_end)
                ensure_occurrences_for_task(db, task, immediate_end, workdays, restdays, IMMEDIATE_WINDOW_DAYS)
                if task.recurrence_type != "NONE":
                    enqueue_maintenance_job(db, task.id, "ENSURE", immediate_end + timedelta(days=1))
                action.weekdays = [int(value) for value in (task.weekdays or "").split(",") if value]
                action.month_day = int(task.month_day) if task.month_day else None
                action.nth_week = int(task.nth_week) if task.nth_week else None
                action.nth_weekday = int(task.nth_weekday) if task.nth_weekday is not None else None
                action.recurrence_month = int(task.recurrence_month) if task.recurrence_month else None
                anchor_row = (
                    db.query(ScheduleOccurrence.id)
                    .filter(
                        ScheduleOccurrence.task_id == task.id,
                        ScheduleOccurrence.status != "deleted",
                        ScheduleOccurrence.scheduled_date >= task.start_date,
                    )
                    .order_by(ScheduleOccurrence.scheduled_date)
                    .first()
                )
                link.completion_occurrence_id = anchor_row[0] if anchor_row else None
            else:
                task.title = action.title
                db.query(ScheduleOccurrence).filter(
                    ScheduleOccurrence.task_id == task.id,
                    ScheduleOccurrence.status == "pending",
                ).update({ScheduleOccurrence.title: action.title}, synchronize_session=False)
    db.commit()
    db.refresh(action)
    return serialize_action(db, action)


@router.put("/diary-actions/{action_id}/completion", response_model=DiaryActionResponse)
def complete_diary_action(
    action_id: UUID,
    data: DiaryActionCompletion,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    action = get_owned_action(db, action_id, current_user.id)
    set_action_completion(db, action, data.completed)
    db.commit()
    db.refresh(action)
    return serialize_action(db, action)


@router.post("/diaries/{diary_id}/actions/sync", response_model=list[DiaryActionResponse], status_code=status.HTTP_200_OK)
def sync_diary_actions(
    diary_id: UUID,
    data: DiaryActionSyncRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _owned_analyzed_diary(diary_id, db, current_user)
    action_ids = [item.action_id for item in data.items]
    if len(action_ids) != len(set(action_ids)):
        raise HTTPException(status_code=400, detail="同步列表包含重复行动项")
    synced = []
    for request_item in data.items:
        action = get_owned_action(db, request_item.action_id, current_user.id)
        if action.diary_id != diary_id:
            raise HTTPException(status_code=404, detail="行动项不存在")
        existing_link = (
            db.query(DiaryActionScheduleLink)
            .filter(
                DiaryActionScheduleLink.action_item_id == action.id,
                DiaryActionScheduleLink.unlinked_at.is_(None),
            )
            .first()
        )
        if existing_link:
            synced.append(action)
            continue
        payload = request_item.schedule
        task, occurrence = _create_schedule_task(db, current_user.id, payload, action.title)
        action.title = (payload.title or action.title).strip()
        action.is_all_day = payload.is_all_day
        action.start_date = payload.start_date
        action.start_time = payload.start_time
        action.end_time = payload.end_time
        action.recurrence_type = payload.recurrence_type
        action.interval = payload.interval
        action.weekdays = [int(value) for value in (task.weekdays or "").split(",") if value != ""]
        action.month_day = int(task.month_day) if task.month_day else None
        action.nth_week = int(task.nth_week) if task.nth_week else None
        action.nth_weekday = int(task.nth_weekday) if task.nth_weekday is not None else None
        action.recurrence_month = int(task.recurrence_month) if task.recurrence_month else None
        action.recurrence_until = payload.recurrence_until
        action.recurrence_count = payload.recurrence_count
        action.user_modified = True
        link = DiaryActionScheduleLink(
            user_id=current_user.id,
            action_item_id=action.id,
            schedule_task_id=task.id,
            schedule_task_snapshot_id=task.id,
            completion_occurrence_id=occurrence.id,
        )
        db.add(link)
        if action.status == "completed":
            occurrence.status = "completed"
            occurrence.completed_at = action.completed_at or datetime.utcnow()
        synced.append(action)
    db.commit()
    return [serialize_action(db, action) for action in synced]


@router.delete("/diary-actions/{action_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_diary_action(action_id: UUID, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    action = get_owned_action(db, action_id, current_user.id)
    link = (
        db.query(DiaryActionScheduleLink)
        .filter(DiaryActionScheduleLink.action_item_id == action.id, DiaryActionScheduleLink.unlinked_at.is_(None))
        .first()
    )
    if link:
        link.unlinked_at = datetime.utcnow()
        link.unlink_reason = "ACTION_DELETED"
        link.schedule_task_id = None
        link.completion_occurrence_id = None
    action.deleted_at = datetime.utcnow()
    db.commit()
