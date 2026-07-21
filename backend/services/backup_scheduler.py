"""系统定时备份调度器。调度器要求应用以单 worker 运行。"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta
from typing import Optional
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from config import settings
from database import SessionLocal
from models.backup import BackupRestoreRecord
from models.user import User
from services.backup_restore import create_export_package

logger = logging.getLogger("app.backup_scheduler")


def parse_schedule_time(value: str):
    """解析定时备份时间，格式必须为 HH:MM。"""
    try:
        hour_text, minute_text = value.split(":")
        hour, minute = int(hour_text), int(minute_text)
    except (AttributeError, TypeError, ValueError) as exc:
        raise ValueError("BACKUP_SCHEDULE_TIME 必须使用 HH:MM 格式") from exc
    if not (0 <= hour <= 23 and 0 <= minute <= 59) or len(hour_text) != 2 or len(minute_text) != 2:
        raise ValueError("BACKUP_SCHEDULE_TIME 必须使用 HH:MM 格式")
    from datetime import time
    return time(hour=hour, minute=minute)


def get_schedule_timezone() -> ZoneInfo:
    try:
        return ZoneInfo(settings.BACKUP_SCHEDULE_TIMEZONE)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise ValueError(
            f"BACKUP_SCHEDULE_TIMEZONE 不是有效的 IANA 时区: {settings.BACKUP_SCHEDULE_TIMEZONE}"
        ) from exc


def next_scheduled_run(now: Optional[datetime] = None) -> datetime:
    """计算严格晚于当前时间的下一次触发时间，不执行启动补偿。"""
    timezone = get_schedule_timezone()
    schedule_time = parse_schedule_time(settings.BACKUP_SCHEDULE_TIME)
    current = now.astimezone(timezone) if now else datetime.now(timezone)
    candidate = datetime.combine(current.date(), schedule_time, tzinfo=timezone)
    if candidate <= current:
        candidate += timedelta(days=1)
    return candidate


def validate_backup_schedule_config() -> None:
    parse_schedule_time(settings.BACKUP_SCHEDULE_TIME)
    get_schedule_timezone()


def _create_scheduled_export() -> None:
    db = SessionLocal()
    record = None
    try:
        operator = db.query(User).filter(User.username == "admin").first()
        if operator is None:
            raise RuntimeError("定时备份找不到 admin 管理员账号")
        now = datetime.utcnow()
        record = BackupRestoreRecord(
            operation_type="export",
            status="pending",
            scope_type="all",
            scope_summary=f"来源=定时备份；范围=all；计划日期={now.date().isoformat()}",
            operator_user_id=operator.id,
            current_phase="等待中",
        )
        db.add(record)
        db.commit()
        db.refresh(record)
        create_export_package(db, record, "all", None, None, None)
    except Exception as exc:
        logger.exception("定时备份失败 record_id=%s", getattr(record, "id", None))
        if record is not None:
            db.rollback()
            record = db.get(BackupRestoreRecord, record.id)
            if record:
                record.status = "failed"
                record.current_phase = "失败"
                record.error_summary = f"{type(exc).__name__}: {exc}"
                record.finished_at = datetime.utcnow()
                db.commit()
        raise
    finally:
        db.close()


async def run_scheduled_backup_with_retry() -> None:
    """执行一次定时备份，失败后立即重试一次。"""
    for attempt in range(1, 3):
        try:
            await asyncio.to_thread(_create_scheduled_export)
            logger.info("定时备份成功 attempt=%d", attempt)
            return
        except Exception:
            if attempt == 2:
                logger.exception("定时备份重试后仍失败")
                return
            logger.exception("定时备份失败，将立即重试")


class BackupScheduler:
    def __init__(self) -> None:
        self._runner: Optional[asyncio.Task] = None
        self._tasks: set[asyncio.Task] = set()
        self._stopping = False

    async def start(self) -> None:
        if self._runner and not self._runner.done():
            return
        validate_backup_schedule_config()
        self._stopping = False
        self._runner = asyncio.create_task(self._run(), name="backup-scheduler")
        logger.info(
            "定时备份调度器已启动，触发时间=%s 时区=%s",
            settings.BACKUP_SCHEDULE_TIME,
            settings.BACKUP_SCHEDULE_TIMEZONE,
        )

    async def stop(self) -> None:
        self._stopping = True
        if self._runner:
            self._runner.cancel()
            await asyncio.gather(self._runner, return_exceptions=True)
        if self._tasks:
            await asyncio.gather(*self._tasks, return_exceptions=True)
        logger.info("定时备份调度器已停止")

    async def _run(self) -> None:
        while not self._stopping:
            next_run = next_scheduled_run()
            delay = max(0.0, (next_run - datetime.now(next_run.tzinfo)).total_seconds())
            logger.info("下一次定时备份时间=%s", next_run.isoformat())
            await asyncio.sleep(delay)
            if self._stopping:
                return
            task = asyncio.create_task(run_scheduled_backup_with_retry(), name="scheduled-backup")
            self._tasks.add(task)
            task.add_done_callback(self._tasks.discard)


backup_scheduler = BackupScheduler()
