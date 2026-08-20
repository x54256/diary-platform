"""定期回顾持久化任务队列与自动调度。"""

from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import date, datetime, timedelta

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from database import SessionLocal
from models.review import (
    Review,
    ReviewGenerationMode,
    ReviewTask,
    ReviewTaskStatus,
    ReviewTaskStep,
    ReviewTaskTriggerType,
    ReviewType,
)
from models.user import User
from services.review_generation import LEASE_DURATION
from services.review_workflow import execute_review_graph
from services.task_environment import TASK_ENVIRONMENT
from services.model_runtime import ModelRuntimeError, resolve_model_setting
from services.review_periods import (
    ReviewPeriod,
    is_generation_due,
    recent_completed_periods,
    week_bounds,
)


logger = logging.getLogger("app.review_tasks")
TERMINAL_STATUSES = {
    ReviewTaskStatus.SUCCEEDED.value,
    ReviewTaskStatus.FAILED.value,
    ReviewTaskStatus.SKIPPED_NO_DATA.value,
}
ACTIVE_STATUSES = {ReviewTaskStatus.PENDING_START.value, ReviewTaskStatus.QUEUED.value, ReviewTaskStatus.RUNNING.value}


class ReviewTaskError(ValueError):
    pass


def get_or_create_review(db: Session, user_id: uuid.UUID, period: ReviewPeriod) -> Review:
    review = db.query(Review).filter(
        Review.user_id == user_id,
        Review.review_type == period.review_type,
        Review.period_start == period.start,
        Review.period_end == period.end,
    ).first()
    if review:
        return review
    review = Review(
        user_id=user_id,
        review_type=period.review_type,
        period_start=period.start,
        period_end=period.end,
    )
    db.add(review)
    db.flush()
    return review


def month_dependencies_terminal(db: Session, user_id: uuid.UUID, period: ReviewPeriod) -> bool:
    if period.review_type != ReviewType.MONTH.value:
        return True
    cursor, _ = week_bounds(period.start)
    while cursor <= period.end:
        end = cursor + timedelta(days=6)
        review = db.query(Review).filter(
            Review.user_id == user_id,
            Review.review_type == ReviewType.WEEK.value,
            Review.period_start == cursor,
            Review.period_end == end,
        ).first()
        if not review:
            # 已到月回顾允许生成的时间时，缺少整个周回顾本身就是一种
            # 可披露的缺失依赖，不能永久阻塞上级回顾。
            cursor += timedelta(days=7)
            continue
        latest = db.query(ReviewTask).filter(
            ReviewTask.environment == TASK_ENVIRONMENT,
            ReviewTask.review_id == review.id,
        ).order_by(
            ReviewTask.created_at.desc()
        ).first()
        if not latest or latest.status not in TERMINAL_STATUSES:
            return False
        cursor += timedelta(days=7)
    return True


def start_blocking_dependencies(db: Session, user_id: uuid.UUID, period: ReviewPeriod) -> list[str]:
    """返回未完成的必需下级周期；首次任务创建不阻塞，只有启动阻塞。"""
    if period.review_type != ReviewType.MONTH.value:
        return []
    blockers: list[str] = []
    cursor, _ = week_bounds(period.start)
    while cursor <= period.end:
        end = cursor + timedelta(days=6)
        review = db.query(Review).filter(
            Review.user_id == user_id,
            Review.review_type == ReviewType.WEEK.value,
            Review.period_start == cursor,
            Review.period_end == end,
        ).first()
        latest = (
            db.query(ReviewTask).filter(
                ReviewTask.environment == TASK_ENVIRONMENT,
                ReviewTask.review_id == review.id,
            ).order_by(ReviewTask.created_at.desc()).first()
            if review else None
        )
        if not review or not (
            review.current_version_id
            or (latest and latest.status == ReviewTaskStatus.SKIPPED_NO_DATA.value)
        ):
            blockers.append(f"周回顾 {cursor.isoformat()} 至 {end.isoformat()}")
        cursor += timedelta(days=7)
    return blockers


def create_first_generation_task(
    db: Session,
    user_id: uuid.UUID,
    period: ReviewPeriod,
    *,
    trigger_type: str = ReviewTaskTriggerType.MANUAL.value,
) -> ReviewTask:
    if period.review_type not in {ReviewType.WEEK.value, ReviewType.MONTH.value}:
        raise ReviewTaskError("当前只支持周回顾和月回顾")
    if not is_generation_due(period):
        raise ReviewTaskError("只能生成已经自然结束并满足生成时间的周期")
    review = get_or_create_review(db, user_id, period)
    if review.current_version_id:
        raise ReviewTaskError("这个周期已有回顾")
    active = db.query(ReviewTask).filter(
        ReviewTask.environment == TASK_ENVIRONMENT,
        ReviewTask.review_id == review.id,
        ReviewTask.status.in_(ACTIVE_STATUSES),
    ).first()
    if active:
        return active
    task = ReviewTask(
        review_id=review.id,
        user_id=user_id,
        trigger_type=trigger_type,
        generation_mode=ReviewGenerationMode.FULL.value,
        status=ReviewTaskStatus.PENDING_START.value,
        current_step=ReviewTaskStep.FREEZE_SOURCES.value,
    )
    db.add(task)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        existing = db.query(ReviewTask).filter(
            ReviewTask.environment == TASK_ENVIRONMENT,
            ReviewTask.review_id == review.id,
            ReviewTask.status.in_(ACTIVE_STATUSES),
        ).first()
        if existing:
            return existing
        raise
    db.refresh(task)
    return task


def create_regeneration_task(
    db: Session,
    review: Review,
    *,
    base_version_id: uuid.UUID,
    generation_mode: str,
) -> ReviewTask:
    active = db.query(ReviewTask).filter(
        ReviewTask.environment == TASK_ENVIRONMENT,
        ReviewTask.review_id == review.id,
        ReviewTask.status.in_(ACTIVE_STATUSES),
    ).first()
    if active:
        return active
    step = (
        ReviewTaskStep.LOAD_BASE_EVENT.value
        if generation_mode == ReviewGenerationMode.ANALYSIS_ONLY.value
        else ReviewTaskStep.FREEZE_SOURCES.value
    )
    task = ReviewTask(
        review_id=review.id,
        user_id=review.user_id,
        trigger_type=ReviewTaskTriggerType.REGENERATE.value,
        generation_mode=generation_mode,
        base_version_id=base_version_id,
        status=ReviewTaskStatus.QUEUED.value,
        current_step=step,
    )
    db.add(task)
    db.commit()
    db.refresh(task)
    return task


def create_retry_task(db: Session, failed: ReviewTask) -> ReviewTask:
    if failed.status != ReviewTaskStatus.FAILED.value:
        raise ReviewTaskError("只能重试失败的回顾任务")
    active = db.query(ReviewTask).filter(
        ReviewTask.environment == TASK_ENVIRONMENT,
        ReviewTask.review_id == failed.review_id,
        ReviewTask.status.in_(ACTIVE_STATUSES),
    ).first()
    if active:
        return active
    # 断点恢复必须保留同一 task_id：每日产物和 LangGraph checkpoint 都以它为键。
    task = failed
    task.status = ReviewTaskStatus.QUEUED.value
    task.trigger_type = ReviewTaskTriggerType.RETRY.value
    task.run_token = None
    task.lease_until = None
    task.available_at = datetime.utcnow()
    task.completed_at = None
    task.error_code = None
    task.error_message = None
    task.current_step = (
        ReviewTaskStep.LOAD_BASE_EVENT.value
        if task.generation_mode == ReviewGenerationMode.ANALYSIS_ONLY.value
        else ReviewTaskStep.PERSIST_VERSION.value
        if isinstance(task.analysis_result, dict) and "domains" in task.analysis_result
        else ReviewTaskStep.ANALYSIS_ACTION.value
        if isinstance(task.event_result, dict) and "domains" in task.event_result
        else ReviewTaskStep.EVENT_ORGANIZE.value if task.source_snapshot_ready else ReviewTaskStep.FREEZE_SOURCES.value
    )
    db.commit()
    db.refresh(task)
    return task


class ReviewTaskManager:
    def __init__(self) -> None:
        self._runner: asyncio.Task | None = None
        self._active: dict[uuid.UUID, asyncio.Task] = {}
        self._wake = asyncio.Event()
        self._stopping = False
        self._last_auto_scan: datetime | None = None
        self._startup_recovery_cutoff: datetime | None = None

    async def start(self) -> None:
        if self._runner and not self._runner.done():
            return
        self._stopping = False
        self._startup_recovery_cutoff = datetime.utcnow()
        self._runner = asyncio.create_task(self._run(), name="review-task-manager")
        asyncio.create_task(
            self._recover_interrupted_tasks_after_start(self._startup_recovery_cutoff),
            name="review-task-startup-recovery",
        )

    async def stop(self) -> None:
        self._stopping = True
        self._wake.set()
        if self._runner:
            await self._runner
        if self._active:
            await asyncio.gather(*self._active.values(), return_exceptions=True)
        self._runner = None

    def wake(self) -> None:
        self._wake.set()

    def start_claimed_task(self, task_id: uuid.UUID, token: uuid.UUID) -> None:
        """启动已在当前事务中认领的任务。"""
        self._active[task_id] = asyncio.create_task(
            self._run_task(task_id, token),
            name=f"review-task-{task_id}",
        )

    async def _recover_interrupted_tasks_after_start(self, cutoff: datetime) -> None:
        try:
            await asyncio.to_thread(self._fail_interrupted_tasks_on_start, cutoff)
        finally:
            self._startup_recovery_cutoff = None
            self.wake()

    def _fail_interrupted_tasks_on_start(self, interrupted_before: datetime | None = None) -> None:
        db = SessionLocal()
        try:
            db.execute(text("SET LOCAL lock_timeout = '1s'"))
            query = db.query(ReviewTask).filter(
                ReviewTask.environment == TASK_ENVIRONMENT,
                ReviewTask.status.in_([
                    ReviewTaskStatus.QUEUED.value,
                    ReviewTaskStatus.RUNNING.value,
                ])
            )
            if interrupted_before is not None:
                query = query.filter(ReviewTask.updated_at < interrupted_before)
            interrupted = query.with_for_update(skip_locked=True).all()
            for task in interrupted:
                task.status = ReviewTaskStatus.FAILED.value
                task.lease_until = None
                task.run_token = None
                task.completed_at = datetime.utcnow()
                task.error_code = "APP_RESTARTED"
                task.error_message = "应用重启导致任务中断，请重试。"
            db.commit()
        except SQLAlchemyError:
            db.rollback()
            logger.exception("应用启动时标记中断回顾任务失败")
        finally:
            db.close()

    def _claim(self) -> tuple[uuid.UUID, uuid.UUID] | None:
        db = SessionLocal()
        try:
            now = datetime.utcnow()
            expired = db.query(ReviewTask).filter(
                ReviewTask.environment == TASK_ENVIRONMENT,
                ReviewTask.status == ReviewTaskStatus.RUNNING.value,
                ReviewTask.lease_until.isnot(None),
                ReviewTask.lease_until < now,
            ).with_for_update(skip_locked=True).all()
            for stale in expired:
                stale.status = ReviewTaskStatus.QUEUED.value
                stale.run_token = None
                stale.lease_until = None
                stale.available_at = now
                if stale.generation_mode == ReviewGenerationMode.ANALYSIS_ONLY.value:
                    stale.current_step = ReviewTaskStep.LOAD_BASE_EVENT.value
                else:
                    stale.current_step = (
                        ReviewTaskStep.PERSIST_VERSION.value
                        if isinstance(stale.analysis_result, dict) and "domains" in stale.analysis_result
                        else ReviewTaskStep.ANALYSIS_ACTION.value
                        if isinstance(stale.event_result, dict) and "domains" in stale.event_result
                        else ReviewTaskStep.EVENT_ORGANIZE.value
                        if stale.source_snapshot_ready and stale.source_set_id
                        else ReviewTaskStep.FREEZE_SOURCES.value
                    )
            if expired:
                db.flush()
            task = db.query(ReviewTask).filter(
                ReviewTask.environment == TASK_ENVIRONMENT,
                ReviewTask.status == ReviewTaskStatus.QUEUED.value,
                ReviewTask.available_at <= now,
                ReviewTask.updated_at >= self._startup_recovery_cutoff
                if self._startup_recovery_cutoff else True,
            ).order_by(ReviewTask.created_at).with_for_update(skip_locked=True).first()
            if not task:
                db.rollback()
                return None
            token = uuid.uuid4()
            task.status = ReviewTaskStatus.RUNNING.value
            task.run_token = token
            task.started_at = task.started_at or now
            task.lease_until = now + LEASE_DURATION
            task.error_code = None
            task.error_message = None
            db.commit()
            return task.id, token
        finally:
            db.close()

    async def _run_task(self, task_id: uuid.UUID, token: uuid.UUID) -> None:
        heartbeat = asyncio.create_task(self._heartbeat(task_id, token), name=f"review-heartbeat-{task_id}")
        try:
            await execute_review_graph(task_id, token)
        except Exception:
            # 业务执行函数已将失败状态和用户可见错误写回任务；此处只避免遗留未获取的 asyncio 异常。
            logger.exception("回顾任务工作流异常 task_id=%s", task_id)
        finally:
            heartbeat.cancel()
            await asyncio.gather(heartbeat, return_exceptions=True)
            self._active.pop(task_id, None)
            self._wake.set()

    @staticmethod
    def _heartbeat_sync(task_id: uuid.UUID, token: uuid.UUID) -> None:
        db = SessionLocal()
        try:
            db.query(ReviewTask).filter(
                ReviewTask.id == task_id,
                ReviewTask.run_token == token,
                ReviewTask.status == ReviewTaskStatus.RUNNING.value,
            ).update({ReviewTask.lease_until: datetime.utcnow() + LEASE_DURATION}, synchronize_session=False)
            db.commit()
        finally:
            db.close()

    async def _heartbeat(self, task_id: uuid.UUID, token: uuid.UUID) -> None:
        while True:
            await asyncio.sleep(30)
            await asyncio.to_thread(self._heartbeat_sync, task_id, token)

    async def _run(self) -> None:
        while not self._stopping:
            self._active = {key: value for key, value in self._active.items() if not value.done()}
            if len(self._active) < 2:
                claimed = await asyncio.to_thread(self._claim)
                if claimed:
                    task_id, token = claimed
                    self._active[task_id] = asyncio.create_task(
                        self._run_task(task_id, token),
                        name=f"review-task-{task_id}",
                    )
                    continue
            now = datetime.utcnow()
            if not self._last_auto_scan or now - self._last_auto_scan >= timedelta(minutes=1):
                await asyncio.to_thread(self._create_due_tasks)
                self._last_auto_scan = now
            self._wake.clear()
            try:
                await asyncio.wait_for(self._wake.wait(), timeout=2)
            except asyncio.TimeoutError:
                pass

    def _create_due_tasks(self) -> None:
        db = SessionLocal()
        try:
            for user_id, in db.query(User.id).all():
                for review_type in (ReviewType.WEEK.value, ReviewType.MONTH.value):
                    period = recent_completed_periods(review_type, limit=1)[0]
                    review = db.query(Review).filter(
                        Review.user_id == user_id,
                        Review.review_type == period.review_type,
                        Review.period_start == period.start,
                        Review.period_end == period.end,
                    ).first()
                    if review and (review.current_version_id or review.tasks):
                        continue
                    try:
                        create_first_generation_task(
                            db,
                            user_id,
                            period,
                            trigger_type=ReviewTaskTriggerType.AUTO.value,
                        )
                    except ReviewTaskError:
                        db.rollback()
            db.commit()
        except Exception:
            db.rollback()
            logger.exception("自动创建回顾任务失败")
        finally:
            db.close()


review_task_manager = ReviewTaskManager()
