"""日程实例窗口维护调度器。应用以单 worker 运行时启用。"""

from __future__ import annotations

import asyncio
import logging
from datetime import date, datetime, time, timedelta
from typing import Optional
from zoneinfo import ZoneInfo

from database import SessionLocal
from models.schedule import ScheduleMaintenanceJob, ScheduleOccurrence, ScheduleTask
from models.user import User
from routers.schedules import WINDOW_DAYS, ensure_occurrences

logger = logging.getLogger("app.schedule_occurrence_scheduler")
TIMEZONE = ZoneInfo("Asia/Shanghai")
RUN_TIME = time(hour=0, minute=5)


def next_scheduled_run(now: Optional[datetime] = None) -> datetime:
    current = now.astimezone(TIMEZONE) if now else datetime.now(TIMEZONE)
    candidate = datetime.combine(current.date(), RUN_TIME, tzinfo=TIMEZONE)
    return candidate + timedelta(days=1) if candidate <= current else candidate


def maintain_occurrence_window() -> None:
    db = SessionLocal()
    try:
        horizon = date.today() + timedelta(days=WINDOW_DAYS)
        for user in db.query(User).all():
            ensure_occurrences(db, user, horizon)
        db.commit()
    except Exception:
        db.rollback()
        logger.exception("日程实例窗口补齐失败")
        raise
    finally:
        db.close()


def recover_maintenance_jobs() -> None:
    db = SessionLocal()
    try:
        db.query(ScheduleMaintenanceJob).filter(
            ScheduleMaintenanceJob.status == "running"
        ).update({ScheduleMaintenanceJob.status: "queued"}, synchronize_session=False)
        db.commit()
    except Exception:
        db.rollback()
        logger.exception("恢复日程维护任务失败")
    finally:
        db.close()


def process_next_maintenance_job() -> bool:
    db = SessionLocal()
    job_id = None
    try:
        now = datetime.utcnow()
        job = db.query(ScheduleMaintenanceJob).filter(
            ScheduleMaintenanceJob.status == "queued",
            ScheduleMaintenanceJob.available_at <= now,
        ).order_by(ScheduleMaintenanceJob.created_at).first()
        if not job:
            return False
        job_id = job.id
        job.status = "running"
        job.attempts += 1
        db.commit()

        task = db.query(ScheduleTask).filter(ScheduleTask.id == job.task_id).first()
        if job.operation == "DELETE":
            if task:
                db.query(ScheduleOccurrence).filter(
                    ScheduleOccurrence.task_id == job.task_id,
                    ScheduleOccurrence.scheduled_date >= job.scheduled_from,
                ).delete(synchronize_session=False)
        elif job.operation == "ENSURE" and task and task.recurrence_type != "NONE":
            from routers.schedules import cached_holiday_sets, ensure_occurrences_for_task

            horizon = date.today() + timedelta(days=WINDOW_DAYS)
            workdays, restdays = cached_holiday_sets(db, task, horizon)
            ensure_occurrences_for_task(
                db, task, horizon, workdays, restdays, WINDOW_DAYS, job.scheduled_from
            )
        job.status = "completed"
        job.updated_at = datetime.utcnow()
        db.commit()
        logger.info("日程维护任务完成 job_id=%s operation=%s", job.id, job.operation)
        return True
    except Exception as exc:
        db.rollback()
        if job_id:
            failed_job = db.query(ScheduleMaintenanceJob).filter_by(id=job_id).first()
            if failed_job:
                failed_job.status = "queued" if failed_job.attempts < 3 else "failed"
                failed_job.available_at = datetime.utcnow() + timedelta(minutes=5)
                failed_job.last_error = str(exc)[:2000]
                failed_job.updated_at = datetime.utcnow()
                db.commit()
        logger.exception("日程维护任务失败 job_id=%s", job_id)
        return True
    finally:
        db.close()


class ScheduleOccurrenceScheduler:
    def __init__(self) -> None:
        self._runner: Optional[asyncio.Task] = None
        self._stopping = False

    async def start(self) -> None:
        if self._runner and not self._runner.done():
            return
        await asyncio.to_thread(recover_maintenance_jobs)
        await asyncio.to_thread(maintain_occurrence_window)
        self._stopping = False
        self._runner = asyncio.create_task(self._run(), name="schedule-occurrence-scheduler")
        logger.info("日程实例窗口调度器已启动，触发时间=00:05 Asia/Shanghai")

    async def stop(self) -> None:
        self._stopping = True
        if self._runner:
            self._runner.cancel()
            await asyncio.gather(self._runner, return_exceptions=True)

    async def _run(self) -> None:
        next_run = next_scheduled_run()
        while not self._stopping:
            current = datetime.now(TIMEZONE)
            if current >= next_run:
                await asyncio.to_thread(maintain_occurrence_window)
                next_run = next_scheduled_run()
            await asyncio.to_thread(process_next_maintenance_job)
            await asyncio.sleep(2)


schedule_occurrence_scheduler = ScheduleOccurrenceScheduler()
