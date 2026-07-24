"""日程任务接口。循环任务的实例采用滚动 180 天持久化。"""
import calendar
import logging
from time import perf_counter
from datetime import date, datetime, timedelta
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from database import get_db
from models.schedule import ScheduleMaintenanceJob, ScheduleOccurrence, ScheduleTask
from models.user import User
from schemas.schedule import ScheduleOccurrenceComplete, ScheduleOccurrenceNoteUpdate, ScheduleOccurrenceResponse, ScheduleOccurrenceUpdate, ScheduleTaskCreate
from services.auth import get_current_user
from services.schedule_holidays import ensure_holiday_years, holiday_sets

router = APIRouter(prefix="/api/schedules", tags=["日程管理"])
WINDOW_DAYS = 180
IMMEDIATE_WINDOW_DAYS = 7
logger = logging.getLogger("app.schedules")

def sunday_weekday(value: date) -> int:
    return (value.weekday() + 1) % 7

def _matches_rule(task: ScheduleTask, target: date, workdays: set[date], restdays: set[date]) -> bool:
    if target < task.start_date or (task.recurrence_until and target > task.recurrence_until): return False
    kind, interval = task.recurrence_type, int(task.interval or 1)
    if kind == "NONE": return target == task.start_date
    delta = (target - task.start_date).days
    if kind == "DAILY": return delta % interval == 0
    if kind == "WEEKLY":
        weekdays = {int(x) for x in (task.weekdays or "").split(",") if x != ""}
        return ((delta // 7) % interval == 0) and sunday_weekday(target) in weekdays
    if kind == "MONTHLY_DATE":
        months = (target.year - task.start_date.year) * 12 + target.month - task.start_date.month
        if months < 0 or months % interval: return False
        return target.day == min(int(task.month_day), calendar.monthrange(target.year, target.month)[1])
    if kind == "MONTHLY_NTH_WEEKDAY":
        months = (target.year - task.start_date.year) * 12 + target.month - task.start_date.month
        if months < 0 or months % interval or sunday_weekday(target) != int(task.nth_weekday): return False
        return (target.day - 1) // 7 + 1 == int(task.nth_week)
    if kind == "YEARLY":
        year_delta = target.year - task.start_date.year
        if year_delta < 0 or year_delta % interval or target.month != task.start_date.month: return False
        return target.day == min(task.start_date.day, calendar.monthrange(target.year, target.month)[1])
    if kind == "WORKDAY":
        return target in workdays or (target.weekday() < 5 and target not in restdays)
    if kind == "REST_DAY":
        return target in restdays or (target.weekday() >= 5 and target not in workdays)
    return False

def occurs(task: ScheduleTask, target: date, workdays: set[date] | None = None, restdays: set[date] | None = None) -> bool:
    workdays, restdays = workdays or set(), restdays or set()
    if not _matches_rule(task, target, workdays, restdays):
        return False
    if not task.recurrence_count or task.recurrence_type == "NONE":
        return True
    count = 0
    cursor = task.start_date
    while cursor <= target:
        if _matches_rule(task, cursor, workdays, restdays):
            count += 1
        cursor += timedelta(days=1)
    return count <= int(task.recurrence_count)

def ensure_occurrences_for_task(db: Session, task: ScheduleTask, end: date, workdays: set[date] | None = None, restdays: set[date] | None = None, window_days: int = WINDOW_DAYS, start_from: date | None = None):
    """批量补齐单个日程任务的实例窗口，避免逐日期查询。"""
    start = max(task.start_date, date.today(), start_from or task.start_date)
    horizon = max(end, date.today() + timedelta(days=window_days))
    if task.recurrence_until:
        horizon = min(horizon, task.recurrence_until)
    if start > horizon:
        return 0, 0
    started_at = perf_counter()
    if task.recurrence_type in {"WORKDAY", "REST_DAY"} and workdays is None and restdays is None:
        raise RuntimeError("日程实例生成禁止在请求路径同步获取节假日数据")
    workdays, restdays = workdays or set(), restdays or set()
    existing_dates = {
        value[0] for value in db.query(ScheduleOccurrence.scheduled_date).filter(
            ScheduleOccurrence.task_id == task.id,
            ScheduleOccurrence.scheduled_date >= start,
            ScheduleOccurrence.scheduled_date <= horizon,
        ).all()
    }
    missing_dates = []
    cursor = start
    while cursor <= horizon:
        if occurs(task, cursor, workdays, restdays) and cursor not in existing_dates:
            missing_dates.append(cursor)
        cursor += timedelta(days=1)
    if task.recurrence_type in {"WORKDAY", "REST_DAY"}:
        stale_deleted = 0
        stale = db.query(ScheduleOccurrence).filter(
            ScheduleOccurrence.task_id == task.id,
            ScheduleOccurrence.scheduled_date >= start,
            ScheduleOccurrence.scheduled_date <= horizon,
            ScheduleOccurrence.status == "pending",
            ScheduleOccurrence.manually_modified.is_(False),
        ).all()
        for item in stale:
            if not occurs(task, item.scheduled_date, workdays, restdays):
                db.delete(item)
                stale_deleted += 1
    else:
        stale_deleted = 0
    if missing_dates:
        occurrence_values = [
            {
                "user_id": task.user_id,
                "task_id": task.id,
                "scheduled_date": scheduled_date,
                "title": task.title,
                "is_all_day": task.is_all_day,
                "start_time": task.start_time,
                "end_time": task.end_time,
            }
            for scheduled_date in missing_dates
        ]
        db.execute(
            insert(ScheduleOccurrence)
            .values(occurrence_values)
            .on_conflict_do_nothing(index_elements=["task_id", "scheduled_date"])
        )
    logger.info(
        "日程实例窗口生成完成 task_id=%s start=%s horizon=%s scanned_days=%d missing=%d stale_deleted=%d duration_ms=%d window_days=%d",
        task.id, start, horizon, (horizon - start).days + 1, len(missing_dates),
        stale_deleted,
        int((perf_counter() - started_at) * 1000), window_days,
    )
    return len(missing_dates), (horizon - start).days + 1


def ensure_occurrences(db: Session, user: User, end: date):
    tasks = db.query(ScheduleTask).filter(ScheduleTask.user_id == user.id).all()
    special_tasks = [task for task in tasks if task.recurrence_type in {"WORKDAY", "REST_DAY"}]
    if special_tasks:
        ensure_holiday_years(db, range(date.today().year, end.year + 1))
        workdays, restdays = holiday_sets(db, range(date.today().year, end.year + 1))
    else:
        workdays, restdays = set(), set()
    for task in tasks:
        ensure_occurrences_for_task(db, task, end, workdays, restdays)


def cached_holiday_sets(db: Session, task: ScheduleTask, end: date) -> tuple[set[date], set[date]]:
    if task.recurrence_type not in {"WORKDAY", "REST_DAY"}:
        return set(), set()
    start = max(task.start_date, date.today())
    if task.recurrence_until:
        end = min(end, task.recurrence_until)
    if start > end:
        return set(), set()
    return holiday_sets(db, range(start.year, end.year + 1))


def enqueue_maintenance_job(db: Session, task_id, operation: str, scheduled_from: date) -> None:
    db.add(ScheduleMaintenanceJob(
        task_id=task_id,
        operation=operation,
        scheduled_from=scheduled_from,
    ))

@router.post("", response_model=list[ScheduleOccurrenceResponse], status_code=status.HTTP_201_CREATED)
def create_schedule(data: ScheduleTaskCreate, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    weekdays = data.weekdays or ([sunday_weekday(data.start_date)] if data.recurrence_type == "WEEKLY" else [])
    month_day = data.month_day or (data.start_date.day if data.recurrence_type == "MONTHLY_DATE" else None)
    nth_week = data.nth_week or (((data.start_date.day - 1) // 7) + 1 if data.recurrence_type == "MONTHLY_NTH_WEEKDAY" else None)
    nth_weekday = data.nth_weekday if data.nth_weekday is not None else (sunday_weekday(data.start_date) if data.recurrence_type == "MONTHLY_NTH_WEEKDAY" else None)
    task = ScheduleTask(user_id=current_user.id, title=data.title, is_all_day=data.is_all_day, start_date=data.start_date,
        start_time=data.start_time, end_time=data.end_time, recurrence_type=data.recurrence_type, interval=str(data.interval),
        weekdays=",".join(map(str, weekdays)) or None, month_day=str(month_day) if month_day else None,
        nth_week=str(nth_week) if nth_week else None, nth_weekday=str(nth_weekday) if nth_weekday is not None else None,
        recurrence_until=data.recurrence_until, recurrence_count=str(data.recurrence_count) if data.recurrence_count else None)
    db.add(task); db.flush()
    immediate_end = data.start_date + timedelta(days=IMMEDIATE_WINDOW_DAYS - 1)
    workdays, restdays = cached_holiday_sets(db, task, immediate_end)
    ensure_occurrences_for_task(db, task, immediate_end, workdays, restdays, IMMEDIATE_WINDOW_DAYS)
    if task.recurrence_type != "NONE":
        enqueue_maintenance_job(db, task.id, "ENSURE", immediate_end + timedelta(days=1))
    db.commit()
    return db.query(ScheduleOccurrence).filter(ScheduleOccurrence.task_id == task.id).order_by(ScheduleOccurrence.scheduled_date).all()

@router.get("", response_model=list[ScheduleOccurrenceResponse])
def list_schedules(start_date: date = Query(...), end_date: date = Query(...), db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    if end_date < start_date: raise HTTPException(400, "结束日期不能早于开始日期")
    return db.query(ScheduleOccurrence).filter(ScheduleOccurrence.user_id == current_user.id,
        ScheduleOccurrence.status != "deleted",
        ScheduleOccurrence.scheduled_date >= start_date, ScheduleOccurrence.scheduled_date <= end_date).order_by(
        ScheduleOccurrence.scheduled_date, ScheduleOccurrence.is_all_day.desc(), ScheduleOccurrence.start_time, ScheduleOccurrence.created_at).all()

@router.put("/occurrences/{occurrence_id}/completion", response_model=ScheduleOccurrenceResponse)
def complete_occurrence(occurrence_id: UUID, data: ScheduleOccurrenceComplete, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    item = db.query(ScheduleOccurrence).filter_by(id=occurrence_id, user_id=current_user.id).first()
    if not item: raise HTTPException(404, "日程实例不存在")
    if data.completed:
        item.status, item.completed_at = "completed", datetime.utcnow()
    else:
        item.status, item.completed_at = "pending", None
    db.commit(); db.refresh(item); return item

@router.put("/occurrences/{occurrence_id}/note", response_model=ScheduleOccurrenceResponse)
def update_occurrence_note(occurrence_id: UUID, data: ScheduleOccurrenceNoteUpdate, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    item = db.query(ScheduleOccurrence).filter_by(id=occurrence_id, user_id=current_user.id).first()
    if not item: raise HTTPException(404, "日程实例不存在")
    item.execution_note = data.execution_note
    db.commit(); db.refresh(item); return item

@router.put("/occurrences/{occurrence_id}", response_model=ScheduleOccurrenceResponse)
def update_occurrence(occurrence_id: UUID, data: ScheduleOccurrenceUpdate, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    item = db.query(ScheduleOccurrence).filter_by(id=occurrence_id, user_id=current_user.id).first()
    if not item: raise HTTPException(404, "日程实例不存在")
    if data.recurrence_until and data.recurrence_until < item.scheduled_date:
        raise HTTPException(400, "截止日期不能早于当前日程日期")
    old_task = item.task
    repeat_changed = any([
        data.recurrence_type != old_task.recurrence_type,
        data.recurrence_until != old_task.recurrence_until,
        (data.recurrence_count or None) != (int(old_task.recurrence_count) if old_task.recurrence_count else None),
        data.interval != int(old_task.interval or 1),
        data.weekdays != [int(value) for value in (old_task.weekdays or '').split(',') if value != ''],
        (data.month_day or None) != (int(old_task.month_day) if old_task.month_day else None),
        (data.nth_week or None) != (int(old_task.nth_week) if old_task.nth_week else None),
        (data.nth_weekday if data.nth_weekday is not None else None) != (int(old_task.nth_weekday) if old_task.nth_weekday else None),
    ])
    if repeat_changed:
        old_task.recurrence_until = item.scheduled_date - timedelta(days=1)
        immediate_end = item.scheduled_date + timedelta(days=IMMEDIATE_WINDOW_DAYS - 1)
        db.query(ScheduleOccurrence).filter(ScheduleOccurrence.task_id == old_task.id,
            ScheduleOccurrence.scheduled_date >= item.scheduled_date,
            ScheduleOccurrence.scheduled_date <= immediate_end).delete(synchronize_session=False)
        enqueue_maintenance_job(db, old_task.id, "DELETE", immediate_end + timedelta(days=1))
        weekdays = data.weekdays or ([sunday_weekday(item.scheduled_date)] if data.recurrence_type == "WEEKLY" else [])
        month_day = data.month_day or (item.scheduled_date.day if data.recurrence_type == "MONTHLY_DATE" else None)
        nth_week = data.nth_week
        nth_weekday = data.nth_weekday
        new_task = ScheduleTask(user_id=current_user.id, source_task_id=old_task.id, title=data.title,
            is_all_day=data.is_all_day, start_date=item.scheduled_date, start_time=data.start_time,
            end_time=data.end_time, recurrence_type=data.recurrence_type, interval=str(data.interval),
            weekdays=','.join(map(str, weekdays)) or None, month_day=str(month_day) if month_day else None,
            nth_week=str(nth_week) if nth_week else None,
            nth_weekday=str(nth_weekday) if nth_weekday is not None else None,
            recurrence_until=data.recurrence_until,
            recurrence_count=str(data.recurrence_count) if data.recurrence_count else None)
        db.add(new_task); db.flush()
        workdays, restdays = cached_holiday_sets(db, new_task, immediate_end)
        ensure_occurrences_for_task(db, new_task, immediate_end, workdays, restdays, IMMEDIATE_WINDOW_DAYS)
        if new_task.recurrence_type != "NONE":
            enqueue_maintenance_job(db, new_task.id, "ENSURE", immediate_end + timedelta(days=1))
        updated = db.query(ScheduleOccurrence).filter_by(task_id=new_task.id, scheduled_date=item.scheduled_date).first()
        if not updated:
            updated = ScheduleOccurrence(user_id=current_user.id, task_id=new_task.id,
                scheduled_date=item.scheduled_date, title=data.title, is_all_day=data.is_all_day,
                start_time=data.start_time, end_time=data.end_time, status=item.status,
                completed_at=item.completed_at, execution_note=item.execution_note)
            db.add(updated)
        else:
            updated.title, updated.is_all_day = data.title, data.is_all_day
            updated.start_time, updated.end_time = data.start_time, data.end_time
            updated.status, updated.completed_at = item.status, item.completed_at
            updated.execution_note = item.execution_note
    else:
        item.title, item.is_all_day, item.start_time, item.end_time = data.title, data.is_all_day, data.start_time, data.end_time
        item.manually_modified = True
        updated = item
    db.commit(); db.refresh(updated); return updated

@router.delete("/occurrences/{occurrence_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_occurrence(occurrence_id: UUID, scope: str = Query("single", pattern="^(single|following)$"), db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    item = db.query(ScheduleOccurrence).filter_by(id=occurrence_id, user_id=current_user.id).first()
    if not item: raise HTTPException(404, "日程实例不存在")
    if scope == "following" and item.task.recurrence_type != "NONE":
        item.task.recurrence_until = item.scheduled_date - timedelta(days=1)
        immediate_end = item.scheduled_date + timedelta(days=IMMEDIATE_WINDOW_DAYS - 1)
        db.query(ScheduleOccurrence).filter(ScheduleOccurrence.task_id == item.task_id,
            ScheduleOccurrence.scheduled_date >= item.scheduled_date,
            ScheduleOccurrence.scheduled_date <= immediate_end).delete(synchronize_session=False)
        enqueue_maintenance_job(db, item.task_id, "DELETE", immediate_end + timedelta(days=1))
    else:
        item.status = "deleted"
    db.commit()
