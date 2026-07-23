"""日程任务接口。循环任务的实例采用滚动 180 天持久化。"""
from datetime import date, datetime, timedelta
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from database import get_db
from models.schedule import ScheduleOccurrence, ScheduleTask
from models.user import User
from schemas.schedule import ScheduleOccurrenceComplete, ScheduleOccurrenceResponse, ScheduleOccurrenceUpdate, ScheduleTaskCreate
from services.auth import get_current_user

router = APIRouter(prefix="/api/schedules", tags=["日程管理"])
WINDOW_DAYS = 180

def sunday_weekday(value: date) -> int:
    return (value.weekday() + 1) % 7

def occurs(task: ScheduleTask, target: date) -> bool:
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
        import calendar
        return target.day == min(int(task.month_day), calendar.monthrange(target.year, target.month)[1])
    if kind == "MONTHLY_NTH_WEEKDAY":
        months = (target.year - task.start_date.year) * 12 + target.month - task.start_date.month
        if months < 0 or months % interval or sunday_weekday(target) != int(task.nth_weekday): return False
        return (target.day - 1) // 7 + 1 == int(task.nth_week)
    return False

def ensure_occurrences(db: Session, user: User, end: date):
    tasks = db.query(ScheduleTask).filter(ScheduleTask.user_id == user.id).all()
    for task in tasks:
        start, cursor = task.start_date, max(task.start_date, date.today())
        horizon = max(end, date.today() + timedelta(days=WINDOW_DAYS))
        while cursor <= horizon:
            if occurs(task, cursor) and not db.query(ScheduleOccurrence.id).filter_by(task_id=task.id, scheduled_date=cursor).first():
                db.add(ScheduleOccurrence(user_id=user.id, task_id=task.id, scheduled_date=cursor, title=task.title,
                    is_all_day=task.is_all_day, start_time=task.start_time, end_time=task.end_time))
            cursor += timedelta(days=1)

@router.post("", response_model=list[ScheduleOccurrenceResponse], status_code=status.HTTP_201_CREATED)
def create_schedule(data: ScheduleTaskCreate, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    weekdays = data.weekdays or ([sunday_weekday(data.start_date)] if data.recurrence_type == "WEEKLY" else [])
    task = ScheduleTask(user_id=current_user.id, title=data.title, is_all_day=data.is_all_day, start_date=data.start_date,
        start_time=data.start_time, end_time=data.end_time, recurrence_type=data.recurrence_type, interval=str(data.interval),
        weekdays=",".join(map(str, weekdays)) or None, month_day=str(data.month_day) if data.month_day else None,
        nth_week=str(data.nth_week) if data.nth_week else None, nth_weekday=str(data.nth_weekday) if data.nth_weekday is not None else None,
        recurrence_until=data.recurrence_until, recurrence_count=str(data.recurrence_count) if data.recurrence_count else None)
    db.add(task); db.flush(); ensure_occurrences(db, current_user, date.today() + timedelta(days=WINDOW_DAYS)); db.commit()
    return db.query(ScheduleOccurrence).filter(ScheduleOccurrence.task_id == task.id).order_by(ScheduleOccurrence.scheduled_date).all()

@router.get("", response_model=list[ScheduleOccurrenceResponse])
def list_schedules(start_date: date = Query(...), end_date: date = Query(...), db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    if end_date < start_date: raise HTTPException(400, "结束日期不能早于开始日期")
    ensure_occurrences(db, current_user, end_date); db.commit()
    return db.query(ScheduleOccurrence).filter(ScheduleOccurrence.user_id == current_user.id,
        ScheduleOccurrence.status != "deleted",
        ScheduleOccurrence.scheduled_date >= start_date, ScheduleOccurrence.scheduled_date <= end_date).order_by(
        ScheduleOccurrence.scheduled_date, ScheduleOccurrence.is_all_day.desc(), ScheduleOccurrence.start_time, ScheduleOccurrence.created_at).all()

@router.put("/occurrences/{occurrence_id}/completion", response_model=ScheduleOccurrenceResponse)
def complete_occurrence(occurrence_id: UUID, data: ScheduleOccurrenceComplete, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    item = db.query(ScheduleOccurrence).filter_by(id=occurrence_id, user_id=current_user.id).first()
    if not item: raise HTTPException(404, "日程实例不存在")
    if data.completed:
        item.status, item.completed_at, item.overdue_reason = "completed", datetime.utcnow(), data.overdue_reason
    else:
        item.status, item.completed_at, item.overdue_reason = "pending", None, None
    db.commit(); db.refresh(item); return item

@router.put("/occurrences/{occurrence_id}", response_model=ScheduleOccurrenceResponse)
def update_occurrence(occurrence_id: UUID, data: ScheduleOccurrenceUpdate, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    item = db.query(ScheduleOccurrence).filter_by(id=occurrence_id, user_id=current_user.id).first()
    if not item: raise HTTPException(404, "日程实例不存在")
    if data.scope == "following" and item.task.recurrence_type != "NONE":
        old_task = item.task
        old_task.recurrence_until = item.scheduled_date - timedelta(days=1)
        db.query(ScheduleOccurrence).filter(ScheduleOccurrence.task_id == old_task.id,
            ScheduleOccurrence.scheduled_date >= item.scheduled_date).delete(synchronize_session=False)
        new_task = ScheduleTask(user_id=current_user.id, source_task_id=old_task.id, title=data.title,
            is_all_day=data.is_all_day, start_date=item.scheduled_date, start_time=data.start_time,
            end_time=data.end_time, recurrence_type=old_task.recurrence_type, interval=old_task.interval,
            weekdays=old_task.weekdays, month_day=old_task.month_day, nth_week=old_task.nth_week,
            nth_weekday=old_task.nth_weekday, recurrence_until=None, recurrence_count=old_task.recurrence_count)
        db.add(new_task); db.flush(); ensure_occurrences(db, current_user, item.scheduled_date)
        updated = db.query(ScheduleOccurrence).filter_by(task_id=new_task.id, scheduled_date=item.scheduled_date).first()
    else:
        item.title, item.is_all_day, item.start_time, item.end_time = data.title, data.is_all_day, data.start_time, data.end_time
        updated = item
    db.commit(); db.refresh(updated); return updated

@router.delete("/occurrences/{occurrence_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_occurrence(occurrence_id: UUID, scope: str = Query("single", pattern="^(single|following)$"), db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    item = db.query(ScheduleOccurrence).filter_by(id=occurrence_id, user_id=current_user.id).first()
    if not item: raise HTTPException(404, "日程实例不存在")
    if scope == "following" and item.task.recurrence_type != "NONE":
        item.task.recurrence_until = item.scheduled_date - timedelta(days=1)
        db.query(ScheduleOccurrence).filter(ScheduleOccurrence.task_id == item.task_id,
            ScheduleOccurrence.scheduled_date >= item.scheduled_date).delete(synchronize_session=False)
    else:
        item.status = "deleted"
    db.commit()
