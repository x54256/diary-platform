"""搜索索引批量重建的可恢复后台任务。"""

import asyncio
import json
import logging
from datetime import datetime
from typing import Optional

from sqlalchemy.orm import Session

from database import SessionLocal
from models.diary import Diary, DiaryEvent, DiaryOrganized, DiaryStatus
from models.search_rebuild import SearchIndexRebuildJob
from services.embedding_sync import sync_event_embeddings
from services.search_indexing import refresh_event_search_indexes

logger = logging.getLogger("app.search_rebuild")
BATCH_SIZE = 10
MAX_FAILURE_DETAILS = 20


def eligible_events_query(db: Session, start_date, end_date):
    return (
        db.query(DiaryEvent.id)
        .join(DiaryOrganized, DiaryOrganized.id == DiaryEvent.diary_organized_id)
        .join(Diary, Diary.id == DiaryOrganized.diary_id)
        .filter(
            Diary.deleted_at.is_(None),
            Diary.status.in_([DiaryStatus.organized.value, DiaryStatus.analyzed.value]),
            Diary.diary_date >= start_date,
            Diary.diary_date <= end_date,
        )
    )


def count_eligible_events(db: Session, start_date, end_date) -> int:
    return eligible_events_query(db, start_date, end_date).count()


def _append_failure(job: SearchIndexRebuildJob, event_id, exc: Exception) -> None:
    try:
        details = json.loads(job.failure_details or "[]")
    except json.JSONDecodeError:
        details = []
    if len(details) < MAX_FAILURE_DETAILS:
        details.append({"event_id": str(event_id), "reason": f"{type(exc).__name__}: {exc}"[:500]})
        job.failure_details = json.dumps(details, ensure_ascii=False)


def recover_search_index_rebuild_jobs() -> None:
    """服务重启后从已保存游标继续未完成任务。"""
    db = SessionLocal()
    try:
        db.query(SearchIndexRebuildJob).filter(SearchIndexRebuildJob.status == "running").update(
            {SearchIndexRebuildJob.status: "queued"}, synchronize_session=False
        )
        db.commit()
    except Exception:
        db.rollback()
        logger.exception("恢复搜索索引重建任务失败")
    finally:
        db.close()


def process_next_search_index_rebuild_batch() -> bool:
    """处理一个持久化任务的一批事件；每个事件独立提交，保证崩溃可恢复。"""
    db = SessionLocal()
    job_id = None
    try:
        job = (
            db.query(SearchIndexRebuildJob)
            .filter(SearchIndexRebuildJob.status.in_(["queued", "running"]))
            .order_by(SearchIndexRebuildJob.created_at)
            .with_for_update(skip_locked=True)
            .first()
        )
        if job is None:
            return False
        job_id = job.id
        if job.status == "queued":
            job.status = "running"
            job.started_at = job.started_at or datetime.utcnow()
            db.commit()

        query = eligible_events_query(db, job.start_date, job.end_date)
        if job.last_event_id is not None:
            query = query.filter(DiaryEvent.id > job.last_event_id)
        event_ids = [row[0] for row in query.order_by(DiaryEvent.id).limit(BATCH_SIZE).all()]
        if not event_ids:
            job.status = "completed"
            job.finished_at = datetime.utcnow()
            db.commit()
            return True

        for event_id in event_ids:
            db.rollback()
            job = db.get(SearchIndexRebuildJob, job_id)
            if job is None or job.status != "running":
                return True
            try:
                refresh_event_search_indexes(db, event_id)
                sync_event_embeddings(db, event_id)
                job.processed_events += 1
                job.succeeded_events += 1
                job.last_event_id = event_id
                db.commit()
            except Exception as exc:  # 单个事件失败不阻断同范围其他日记。
                db.rollback()
                job = db.get(SearchIndexRebuildJob, job_id)
                if job is None:
                    return True
                job.processed_events += 1
                job.failed_events += 1
                job.last_event_id = event_id
                _append_failure(job, event_id, exc)
                db.commit()
                logger.exception("搜索索引重建事件失败 job_id=%s event_id=%s", job_id, event_id)
        return True
    except Exception:
        db.rollback()
        logger.exception("搜索索引重建批处理失败 job_id=%s", job_id)
        return True
    finally:
        db.close()


class SearchIndexRebuildScheduler:
    def __init__(self) -> None:
        self._runner: Optional[asyncio.Task] = None
        self._stopping = False

    async def start(self) -> None:
        if self._runner and not self._runner.done():
            return
        await asyncio.to_thread(recover_search_index_rebuild_jobs)
        self._stopping = False
        self._runner = asyncio.create_task(self._run(), name="search-index-rebuild-scheduler")

    async def stop(self) -> None:
        self._stopping = True
        if self._runner:
            self._runner.cancel()
            await asyncio.gather(self._runner, return_exceptions=True)

    async def _run(self) -> None:
        while not self._stopping:
            processed = await asyncio.to_thread(process_next_search_index_rebuild_batch)
            await asyncio.sleep(0 if processed else 2)


search_index_rebuild_scheduler = SearchIndexRebuildScheduler()
