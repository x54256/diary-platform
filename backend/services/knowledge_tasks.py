"""知识沉淀数据库任务队列与租约 worker。"""

import asyncio
import logging
from datetime import datetime, timedelta
from uuid import UUID, uuid4

from sqlalchemy import and_, or_

from database import SessionLocal
from models.knowledge import KnowledgeTask
from services.knowledge_ai import KnowledgeAIError
from services.knowledge_workflow import KnowledgeOwnershipLost, KnowledgeWorkflowError, run_knowledge_graph
from services.pipeline import cleanup_checkpoint
from services.task_environment import TASK_ENVIRONMENT

logger = logging.getLogger(__name__)
LEASE_SECONDS = 180
HEARTBEAT_SECONDS = 45
POLL_SECONDS = 3
MAX_CONCURRENCY = 2


class KnowledgeTaskManager:
    def __init__(self) -> None:
        self._loop_task: asyncio.Task | None = None
        self._running: set[asyncio.Task] = set()
        self._wake = asyncio.Event()
        self._stopping = False
        self._event_loop: asyncio.AbstractEventLoop | None = None

    async def start(self) -> None:
        if self._loop_task:
            return
        self._recover_expired()
        await self._cleanup_pending()
        self._stopping = False
        self._event_loop = asyncio.get_running_loop()
        self._loop_task = asyncio.create_task(self._loop(), name="knowledge-task-manager")

    async def stop(self) -> None:
        self._stopping = True
        self._wake.set()
        if self._loop_task:
            await self._loop_task
            self._loop_task = None
        if self._running:
            for task in self._running:
                task.cancel()
            await asyncio.gather(*self._running, return_exceptions=True)
        self._event_loop = None

    def wake(self) -> None:
        if self._event_loop and self._event_loop.is_running():
            self._event_loop.call_soon_threadsafe(self._wake.set)

    async def _loop(self) -> None:
        cleanup_tick = 0
        while not self._stopping:
            self._running = {task for task in self._running if not task.done()}
            while len(self._running) < MAX_CONCURRENCY:
                claimed = self._claim_one()
                if not claimed:
                    break
                task_id, run_token = claimed
                work = asyncio.create_task(self._run_one(task_id, run_token), name=f"knowledge-{task_id}")
                self._running.add(work)
            cleanup_tick += 1
            if cleanup_tick >= 20:
                self._recover_expired()
                await self._cleanup_pending()
                cleanup_tick = 0
            self._wake.clear()
            try:
                await asyncio.wait_for(self._wake.wait(), timeout=POLL_SECONDS)
            except asyncio.TimeoutError:
                pass

    def _recover_expired(self) -> None:
        db = SessionLocal()
        try:
            now = datetime.utcnow()
            db.query(KnowledgeTask).filter(
                KnowledgeTask.environment == TASK_ENVIRONMENT,
                KnowledgeTask.status == "RUNNING", KnowledgeTask.lease_until <= now,
            ).update({
                "status": "QUEUED", "run_token": None, "lease_until": None,
                "available_at": now, "updated_at": now,
            }, synchronize_session=False)
            db.commit()
        except Exception:
            db.rollback()
            logger.exception("恢复过期知识任务失败")
        finally:
            db.close()

    def _claim_one(self) -> tuple[UUID, UUID] | None:
        db = SessionLocal()
        try:
            now = datetime.utcnow()
            task = db.query(KnowledgeTask).filter(
                KnowledgeTask.environment == TASK_ENVIRONMENT,
                KnowledgeTask.status == "QUEUED", KnowledgeTask.available_at <= now,
            ).order_by(KnowledgeTask.created_at).with_for_update(skip_locked=True).first()
            if not task:
                db.rollback()
                return None
            token = uuid4()
            task.status = "RUNNING"
            task.run_token = token
            task.lease_until = now + timedelta(seconds=LEASE_SECONDS)
            task.started_at = task.started_at or now
            task.updated_at = now
            db.commit()
            return task.id, token
        except Exception:
            db.rollback()
            logger.exception("领取知识任务失败")
            return None
        finally:
            db.close()

    async def _run_one(self, task_id: UUID, run_token: UUID) -> None:
        heartbeat = asyncio.create_task(self._heartbeat(task_id, run_token))
        graph = asyncio.create_task(run_knowledge_graph(task_id, run_token))
        try:
            done, _pending = await asyncio.wait(
                {graph, heartbeat}, return_when=asyncio.FIRST_COMPLETED,
            )
            if heartbeat in done and not graph.done():
                heartbeat_result = heartbeat.result()
                if heartbeat_result != "terminal":
                    # 续租失败后立即停止模型调用和图执行；旧 worker 不再写 checkpoint。
                    graph.cancel()
                    await asyncio.gather(graph, return_exceptions=True)
                    return
            await graph
        except KnowledgeOwnershipLost:
            return
        except (KnowledgeWorkflowError, KnowledgeAIError) as exc:
            self._mark_failed(task_id, run_token, exc.code, str(exc))
        except Exception as exc:
            logger.exception("知识任务执行失败", extra={"task_id": str(task_id), "error_type": type(exc).__name__})
            self._mark_failed(task_id, run_token, "INTERNAL_ERROR", "知识沉淀执行失败")
        finally:
            heartbeat.cancel()
            if not graph.done():
                graph.cancel()
            await asyncio.gather(heartbeat, graph, return_exceptions=True)
            status, error_code = self._terminal_status(task_id)
            if status == "SUCCEEDED" or (status == "FAILED" and error_code == "SOURCE_CHANGED"):
                await self._cleanup_task_checkpoint(task_id)
            self._wake.set()

    async def _heartbeat(self, task_id: UUID, run_token: UUID) -> str:
        while True:
            await asyncio.sleep(HEARTBEAT_SECONDS)
            db = SessionLocal()
            try:
                now = datetime.utcnow()
                updated = db.query(KnowledgeTask).filter(
                    KnowledgeTask.id == task_id, KnowledgeTask.environment == TASK_ENVIRONMENT,
                    KnowledgeTask.status == "RUNNING",
                    KnowledgeTask.run_token == run_token, KnowledgeTask.lease_until > now,
                ).update({"lease_until": now + timedelta(seconds=LEASE_SECONDS), "updated_at": now}, synchronize_session=False)
                db.commit()
                if updated != 1:
                    row = db.query(KnowledgeTask.status, KnowledgeTask.run_token).filter(
                        KnowledgeTask.id == task_id, KnowledgeTask.environment == TASK_ENVIRONMENT,
                    ).first()
                    own_publish_completed = bool(
                        row and row.status == "SUCCEEDED" and row.run_token == run_token
                    )
                    return "terminal" if own_publish_completed else "lost"
            except Exception:
                db.rollback()
                logger.exception("知识任务续租失败", extra={"task_id": str(task_id)})
                return "lost"
            finally:
                db.close()

    def _mark_failed(self, task_id: UUID, run_token: UUID, code: str, message: str) -> bool:
        db = SessionLocal()
        try:
            now = datetime.utcnow()
            updated = db.query(KnowledgeTask).filter(
                KnowledgeTask.id == task_id, KnowledgeTask.environment == TASK_ENVIRONMENT,
                KnowledgeTask.status == "RUNNING",
                KnowledgeTask.run_token == run_token, KnowledgeTask.lease_until > now,
            ).update({
                "status": "FAILED", "error_code": code, "error_message": message[:1000],
                "lease_until": None, "completed_at": now, "updated_at": now,
            }, synchronize_session=False)
            db.commit()
            return updated == 1
        except Exception:
            db.rollback()
            logger.exception("更新知识任务失败状态失败", extra={"task_id": str(task_id)})
            return False
        finally:
            db.close()

    def _terminal_status(self, task_id: UUID) -> tuple[str | None, str | None]:
        db = SessionLocal()
        try:
            task = db.query(KnowledgeTask.status, KnowledgeTask.error_code).filter(
                KnowledgeTask.id == task_id, KnowledgeTask.environment == TASK_ENVIRONMENT,
            ).first()
            return (task[0], task[1]) if task else (None, None)
        finally:
            db.close()

    async def _cleanup_task_checkpoint(self, task_id: UUID) -> None:
        try:
            await cleanup_checkpoint(str(task_id))
        except Exception:
            logger.exception("清理知识任务 checkpoint 失败", extra={"task_id": str(task_id)})
            return
        db = SessionLocal()
        try:
            db.query(KnowledgeTask).filter(
                KnowledgeTask.id == task_id, KnowledgeTask.environment == TASK_ENVIRONMENT,
                or_(
                    KnowledgeTask.status == "SUCCEEDED",
                    and_(KnowledgeTask.status == "FAILED", KnowledgeTask.error_code == "SOURCE_CHANGED"),
                ),
            ).update({"checkpoint_cleaned_at": datetime.utcnow()}, synchronize_session=False)
            db.commit()
        finally:
            db.close()

    async def _cleanup_pending(self) -> None:
        db = SessionLocal()
        try:
            ids = [row[0] for row in db.query(KnowledgeTask.id).filter(
                KnowledgeTask.environment == TASK_ENVIRONMENT,
                KnowledgeTask.checkpoint_cleaned_at.is_(None),
                or_(
                    KnowledgeTask.status == "SUCCEEDED",
                    and_(KnowledgeTask.status == "FAILED", KnowledgeTask.error_code == "SOURCE_CHANGED"),
                ),
            ).limit(100).all()]
        finally:
            db.close()
        for task_id in ids:
            await self._cleanup_task_checkpoint(task_id)


knowledge_task_manager = KnowledgeTaskManager()
