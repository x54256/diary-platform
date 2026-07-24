"""日程实例窗口维护调度器。应用以单 worker 运行时启用。"""

from __future__ import annotations

import asyncio
import logging
from datetime import date, datetime, time, timedelta
from typing import Optional
from zoneinfo import ZoneInfo

from database import SessionLocal
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


class ScheduleOccurrenceScheduler:
    def __init__(self) -> None:
        self._runner: Optional[asyncio.Task] = None
        self._stopping = False

    async def start(self) -> None:
        if self._runner and not self._runner.done():
            return
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
        while not self._stopping:
            next_run = next_scheduled_run()
            await asyncio.sleep(max(0.0, (next_run - datetime.now(TIMEZONE)).total_seconds()))
            if not self._stopping:
                await asyncio.to_thread(maintain_occurrence_window)


schedule_occurrence_scheduler = ScheduleOccurrenceScheduler()
