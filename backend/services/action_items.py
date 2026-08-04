"""日记行动项生成、查询和日程关联服务。"""

from __future__ import annotations

import json
from datetime import date, datetime, time, timedelta
from typing import Any
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import and_, or_
from sqlalchemy.orm import Session, joinedload

from models.diary import (
    AnalysisItem,
    AnalysisRun,
    Diary,
    DiaryActionItem,
    DiaryActionScheduleLink,
    DiaryStatus,
)
from models.schedule import ScheduleOccurrence, ScheduleTask


def _as_uuid(value):
    return UUID(str(value)) if not isinstance(value, UUID) else value


def _valid_links_query(db: Session, action_id=None):
    query = db.query(DiaryActionScheduleLink).filter(DiaryActionScheduleLink.unlinked_at.is_(None))
    if action_id is not None:
        query = query.filter(DiaryActionScheduleLink.action_item_id == action_id)
    return query


def _active_link(db: Session, action_id):
    return _valid_links_query(db, action_id).order_by(DiaryActionScheduleLink.linked_at.desc()).first()


def _time_value(value: time | str | None) -> time | None:
    if value is None or isinstance(value, time):
        return value
    return time.fromisoformat(value)


def serialize_action(db: Session, action: DiaryActionItem) -> dict[str, Any]:
    link = _active_link(db, action.id)
    if link and link.schedule_task_id:
        sync_status = "synced"
        task_id = link.schedule_task_id
        occurrence_id = link.completion_occurrence_id
    elif action.schedule_links:
        sync_status = "schedule_deleted"
        task_id = None
        occurrence_id = None
    else:
        sync_status = "unsynced"
        task_id = None
        occurrence_id = None
    return {
        "id": action.id,
        "diary_id": action.diary_id,
        "generation_run_id": action.generation_run_id,
        "source_kind": action.source_kind,
        "source_refs": action.source_refs or {},
        "title": action.title,
        "is_all_day": action.is_all_day,
        "start_date": action.start_date,
        "start_time": action.start_time,
        "end_time": action.end_time,
        "recurrence_type": action.recurrence_type,
        "interval": action.interval,
        "weekdays": action.weekdays or [],
        "month_day": action.month_day,
        "recurrence_month": action.recurrence_month,
        "nth_week": action.nth_week,
        "nth_weekday": action.nth_weekday,
        "recurrence_until": action.recurrence_until,
        "recurrence_count": action.recurrence_count,
        "status": action.status,
        "completed_at": action.completed_at,
        "user_modified": action.user_modified,
        "sort_order": action.sort_order,
        "schedule": {
            "task_id": task_id,
            "occurrence_id": occurrence_id,
            "status": sync_status,
        },
    }


def list_actions(db: Session, diary_id, user_id) -> list[dict[str, Any]]:
    actions = (
        db.query(DiaryActionItem)
        .options(joinedload(DiaryActionItem.schedule_links))
        .filter(
            DiaryActionItem.diary_id == diary_id,
            DiaryActionItem.user_id == user_id,
            DiaryActionItem.deleted_at.is_(None),
        )
        .order_by(DiaryActionItem.sort_order, DiaryActionItem.created_at)
        .all()
    )
    return [serialize_action(db, item) for item in actions]


def get_owned_action(db: Session, action_id, user_id) -> DiaryActionItem:
    action = (
        db.query(DiaryActionItem)
        .options(joinedload(DiaryActionItem.schedule_links))
        .filter(
            DiaryActionItem.id == action_id,
            DiaryActionItem.user_id == user_id,
            DiaryActionItem.deleted_at.is_(None),
        )
        .first()
    )
    if not action:
        raise HTTPException(status_code=404, detail="行动项不存在")
    return action


def _copy_schedule_to_action(action: DiaryActionItem, schedule: Any, title: str | None = None):
    action.title = (title or getattr(schedule, "title", None) or action.title).strip()
    action.is_all_day = bool(schedule.is_all_day)
    action.start_date = schedule.start_date
    action.start_time = schedule.start_time
    action.end_time = schedule.end_time
    action.recurrence_type = schedule.recurrence_type
    action.interval = int(schedule.interval or 1)
    action.weekdays = list(schedule.weekdays or [])
    action.month_day = schedule.month_day
    action.recurrence_month = getattr(schedule, "recurrence_month", None)
    action.nth_week = schedule.nth_week
    action.nth_weekday = schedule.nth_weekday
    action.recurrence_until = schedule.recurrence_until
    action.recurrence_count = schedule.recurrence_count


def _action_schedule_dict(item: dict[str, Any], title: str | None = None):
    schedule = item.get("schedule") or {}
    return {
        "title": title or item.get("title"),
        "is_all_day": bool(schedule.get("is_all_day", item.get("is_all_day", True))),
        "start_date": schedule.get("start_date", item.get("start_date")),
        "start_time": schedule.get("start_time", item.get("start_time")),
        "end_time": schedule.get("end_time", item.get("end_time")),
        "recurrence_type": schedule.get("recurrence_type", item.get("recurrence_type", "NONE")),
        "interval": int(schedule.get("interval", item.get("interval", 1)) or 1),
        "weekdays": schedule.get("weekdays", item.get("weekdays", [])) or [],
        "month_day": schedule.get("month_day", item.get("month_day")),
        "nth_week": schedule.get("nth_week", item.get("nth_week")),
        "nth_weekday": schedule.get("nth_weekday", item.get("nth_weekday")),
        "recurrence_month": schedule.get("recurrence_month", item.get("recurrence_month")),
        "recurrence_until": schedule.get("recurrence_until", item.get("recurrence_until")),
        "recurrence_count": schedule.get("recurrence_count", item.get("recurrence_count")),
    }


def apply_action_planning_result(
    db: Session,
    diary_id,
    user_id,
    generation_run_id,
    action_items: list[dict[str, Any]],
):
    """保存行动规划结果，并保护已经进入用户执行过程的旧行动项。"""
    diary_id = _as_uuid(diary_id)
    user_id = _as_uuid(user_id)
    generation_run_id = _as_uuid(generation_run_id)
    existing = (
        db.query(DiaryActionItem)
        .filter(DiaryActionItem.diary_id == diary_id, DiaryActionItem.deleted_at.is_(None))
        .all()
    )
    protected = [
        item for item in existing
        if item.status == "completed"
        or item.user_modified
        or _active_link(db, item.id) is not None
        or item.source_kind in {"PLAN", "MERGED"}
    ]
    replaceable = [item for item in existing if item not in protected]
    for item in replaceable:
        item.deleted_at = datetime.utcnow()

    created = []
    protected_titles = {item.title.strip() for item in protected}
    sort_order = len(protected)
    for raw in action_items if isinstance(action_items, list) else []:
        if not isinstance(raw, dict):
            continue
        title = str(raw.get("title") or "").strip()
        if not title or title in protected_titles:
            continue
        schedule = raw.get("schedule") if isinstance(raw.get("schedule"), dict) else {}
        start_date = schedule.get("start_date") or date.today()
        if isinstance(start_date, str):
            start_date = date.fromisoformat(start_date)
        if start_date < date.today():
            start_date = date.today()
        start_time = schedule.get("start_time")
        end_time = schedule.get("end_time")
        if isinstance(start_time, str):
            start_time = time.fromisoformat(start_time)
        if isinstance(end_time, str):
            end_time = time.fromisoformat(end_time)
        is_all_day = bool(schedule.get("is_all_day", True))
        if is_all_day:
            start_time = end_time = None
        source_entries = raw.get("source") if isinstance(raw.get("source"), list) else []
        source_keys = [entry.get("source_key") for entry in source_entries if isinstance(entry, dict) and entry.get("source_key")]
        plan_keys = [key for key in source_keys if key.startswith("plan:")]
        suggestion_keys = [key for key in source_keys if key.startswith("suggestion:")]
        if plan_keys and suggestion_keys:
            source_kind = "MERGED"
        elif plan_keys:
            source_kind = "PLAN"
        else:
            source_kind = "SUGGESTION"
        recurrence_type = schedule.get("recurrence_type") or "NONE"
        if recurrence_type not in {"NONE", "DAILY", "WEEKLY", "MONTHLY_DATE", "MONTHLY_NTH_WEEKDAY", "YEARLY", "WORKDAY", "REST_DAY"}:
            recurrence_type = "NONE"
        recurrence_until = schedule.get("recurrence_until")
        if isinstance(recurrence_until, str) and recurrence_until:
            recurrence_until = date.fromisoformat(recurrence_until)
        recurrence_count = schedule.get("recurrence_count")
        if recurrence_count is not None:
            try:
                recurrence_count = int(recurrence_count)
            except (TypeError, ValueError):
                recurrence_count = None
        weekdays = schedule.get("weekdays") if isinstance(schedule.get("weekdays"), list) else []
        source_refs = {
            "source_keys": source_keys,
            "source": source_entries,
            "plans": [entry for entry in source_entries if isinstance(entry, dict) and str(entry.get("source_key", "")).startswith("plan:")],
            "analysis_source_keys": suggestion_keys,
            "analysis_sources": [entry for entry in source_entries if isinstance(entry, dict) and str(entry.get("source_key", "")).startswith("suggestion:")],
            "analysis_item_ids": raw.get("analysis_item_ids") if isinstance(raw.get("analysis_item_ids"), list) else [],
        }
        item = DiaryActionItem(
            user_id=user_id,
            diary_id=diary_id,
            generation_run_id=generation_run_id,
            source_kind=source_kind,
            source_refs=source_refs,
            title=title,
            is_all_day=is_all_day,
            start_date=start_date,
            start_time=start_time,
            end_time=end_time,
            recurrence_type=recurrence_type,
            interval=int(schedule.get("interval") or 1),
            weekdays=weekdays,
            month_day=schedule.get("month_day"),
            recurrence_month=schedule.get("recurrence_month"),
            nth_week=schedule.get("nth_week"),
            nth_weekday=schedule.get("nth_weekday"),
            recurrence_until=recurrence_until,
            recurrence_count=recurrence_count,
            sort_order=sort_order,
        )
        sort_order += 1
        db.add(item)
        created.append(item)
    return protected + created


def update_action_fields(action: DiaryActionItem, title: str | None, schedule: Any | None):
    if title is not None:
        action.title = title.strip()
    if schedule is not None:
        action.is_all_day = schedule.is_all_day
        action.start_date = schedule.start_date
        action.start_time = schedule.start_time
        action.end_time = schedule.end_time
        action.recurrence_type = schedule.recurrence_type
        action.interval = schedule.interval
        action.weekdays = schedule.weekdays
        action.month_day = schedule.month_day
        action.recurrence_month = schedule.recurrence_month
        action.nth_week = schedule.nth_week
        action.nth_weekday = schedule.nth_weekday
        action.recurrence_until = schedule.recurrence_until
        action.recurrence_count = schedule.recurrence_count
    action.user_modified = True
    action.updated_at = datetime.utcnow()


def set_action_completion(db: Session, action: DiaryActionItem, completed: bool):
    link = _active_link(db, action.id)
    if link and link.completion_occurrence_id:
        occurrence = db.query(ScheduleOccurrence).filter(ScheduleOccurrence.id == link.completion_occurrence_id).first()
        if occurrence:
            occurrence.status = "completed" if completed else "pending"
            occurrence.completed_at = datetime.utcnow() if completed else None
    action.status = "completed" if completed else "pending"
    action.completed_at = datetime.utcnow() if completed else None


def sync_action_from_occurrence(db: Session, occurrence: ScheduleOccurrence):
    """日程完成状态回写行动项，只响应完成锚点。"""
    link = (
        db.query(DiaryActionScheduleLink)
        .filter(
            DiaryActionScheduleLink.completion_occurrence_id == occurrence.id,
            DiaryActionScheduleLink.unlinked_at.is_(None),
        )
        .first()
    )
    if not link:
        return
    action = db.query(DiaryActionItem).filter(DiaryActionItem.id == link.action_item_id, DiaryActionItem.deleted_at.is_(None)).first()
    if not action:
        return
    action.status = "completed" if occurrence.status == "completed" else "pending"
    action.completed_at = occurrence.completed_at if occurrence.status == "completed" else None


def sync_action_from_schedule_task(db: Session, task: ScheduleTask, occurrence: ScheduleOccurrence | None, *, scope: str):
    link = (
        db.query(DiaryActionScheduleLink)
        .filter(DiaryActionScheduleLink.schedule_task_id == task.id, DiaryActionScheduleLink.unlinked_at.is_(None))
        .first()
    )
    if not link:
        return
    action = db.query(DiaryActionItem).filter(DiaryActionItem.id == link.action_item_id, DiaryActionItem.deleted_at.is_(None)).first()
    if not action:
        return
    if scope == "single" and task.recurrence_type != "NONE":
        return
    _copy_schedule_to_action(action, task)
    if occurrence is not None and occurrence.id == link.completion_occurrence_id:
        sync_action_from_occurrence(db, occurrence)


def sync_action_after_task_replaced(
    db: Session,
    old_task: ScheduleTask,
    new_task: ScheduleTask,
    occurrence: ScheduleOccurrence | None,
):
    """循环日程“此日程及以后”产生新任务时迁移有效关联。"""
    link = (
        db.query(DiaryActionScheduleLink)
        .filter(DiaryActionScheduleLink.schedule_task_id == old_task.id, DiaryActionScheduleLink.unlinked_at.is_(None))
        .first()
    )
    if not link:
        return
    action = db.query(DiaryActionItem).filter(DiaryActionItem.id == link.action_item_id, DiaryActionItem.deleted_at.is_(None)).first()
    if not action:
        return
    link.schedule_task_id = new_task.id
    link.schedule_task_snapshot_id = new_task.id
    new_anchor = (
        db.query(ScheduleOccurrence)
        .filter(
            ScheduleOccurrence.task_id == new_task.id,
            ScheduleOccurrence.status != "deleted",
        )
        .order_by(ScheduleOccurrence.scheduled_date)
        .first()
    )
    if new_anchor:
        link.completion_occurrence_id = new_anchor.id
    _copy_schedule_to_action(action, new_task)
    if occurrence and occurrence.status == "completed":
        action.status = "completed"
        action.completed_at = occurrence.completed_at


def handle_schedule_occurrence_deleted(db: Session, occurrence: ScheduleOccurrence, scope: str):
    link = (
        db.query(DiaryActionScheduleLink)
        .filter(
            DiaryActionScheduleLink.schedule_task_id == occurrence.task_id,
            DiaryActionScheduleLink.unlinked_at.is_(None),
        )
        .first()
    )
    if not link:
        return
    task = occurrence.task
    if task.recurrence_type == "NONE" or scope == "following":
        link.unlinked_at = datetime.utcnow()
        link.unlink_reason = "SCHEDULE_DELETED"
        link.schedule_task_id = None
        link.completion_occurrence_id = None
        return
    if link.completion_occurrence_id != occurrence.id:
        return
    replacement = (
        db.query(ScheduleOccurrence)
        .filter(
            ScheduleOccurrence.task_id == task.id,
            ScheduleOccurrence.status != "deleted",
            ScheduleOccurrence.scheduled_date > occurrence.scheduled_date,
        )
        .order_by(ScheduleOccurrence.scheduled_date)
        .first()
    )
    if replacement:
        link.completion_occurrence_id = replacement.id
    else:
        link.unlinked_at = datetime.utcnow()
        link.unlink_reason = "SCHEDULE_DELETED"
        link.schedule_task_id = None
        link.completion_occurrence_id = None


def unlink_action_schedule(db: Session, task_id, reason: str):
    links = _valid_links_query(db).filter(DiaryActionScheduleLink.schedule_task_id == task_id).all()
    for link in links:
        link.unlinked_at = datetime.utcnow()
        link.unlink_reason = reason
        link.schedule_task_id = None
        link.completion_occurrence_id = None
