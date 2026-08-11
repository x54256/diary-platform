"""进程内语音转写调度器。所有阻塞数据库和文件操作都在线程池执行。"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta
from urllib.parse import urlsplit, urlunsplit
from uuid import UUID

from config import settings
from database import SessionLocal
from models.diary import Diary, DiaryStatus
from models.transcription import TranscriptionBatch, TranscriptionItem
from services.asr_vocabulary import (
    build_hotword_entries,
    hotword_fingerprint,
    load_vocabulary_state,
    save_vocabulary_state,
)
from services.fun_asr import FunAsrError, HotwordUnsupported, fun_asr_service
from services.minio_storage import MinioStorageError, minio_storage_service

logger = logging.getLogger("transcription.tasks")

ACTIVE_ITEM_STATUSES = {"QUEUED", "SUBMITTING", "SUBMITTED", "RUNNING"}
ACTIVE_BATCH_STATUSES = {"QUEUED", "PROCESSING"}


def compose_transcription_text(base_text: str | None, items: list[TranscriptionItem]) -> str:
    """按用户确认的顺序合并文本，绝不依赖并发完成顺序或 ORM 返回顺序。"""
    ordered_items = sorted(items, key=lambda item: item.sort_order)
    parts = [part.strip() for part in [base_text or "", *[item.transcript_text or "" for item in ordered_items]] if part.strip()]
    return "\n\n".join(parts)


def _mask_download_url(url: str) -> str:
    parsed = urlsplit(url)
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, "", ""))


def remove_file(object_key: str | None) -> bool:
    return minio_storage_service.remove(object_key)


class TranscriptionTaskManager:
    def __init__(self) -> None:
        self._runner: asyncio.Task | None = None
        self._tasks: dict[UUID, asyncio.Task] = {}
        self._stopping = False
        self._vocabulary_lock = asyncio.Lock()

    async def start(self) -> None:
        if self._runner and not self._runner.done():
            return
        self._stopping = False
        await asyncio.to_thread(self._recover_interrupted)
        self._runner = asyncio.create_task(self._run(), name="transcription-scheduler")
        logger.info("语音转写调度器已启动，并发上限=%d", settings.TRANSCRIPTION_MAX_CONCURRENCY)

    async def stop(self) -> None:
        self._stopping = True
        logger.info("语音转写调度器准备停止，运行中任务数=%d", len(self._tasks))
        if self._runner:
            self._runner.cancel()
        tasks = list(self._tasks.values())
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        if self._runner:
            await asyncio.gather(self._runner, return_exceptions=True)
        await fun_asr_service.close()
        logger.info("语音转写调度器已停止")

    async def _run(self) -> None:
        cleanup_tick = 0
        finalize_tick = 0
        while not self._stopping:
            try:
                self._tasks = {item_id: task for item_id, task in self._tasks.items() if not task.done()}
                available = max(0, settings.TRANSCRIPTION_MAX_CONCURRENCY - len(self._tasks))
                if available:
                    item_ids = await asyncio.to_thread(self._claim_items, available, set(self._tasks))
                    if item_ids:
                        logger.info("语音转写调度器领取任务 item_ids=%s available=%s", item_ids, available)
                    for item_id in item_ids:
                        self._tasks[item_id] = asyncio.create_task(self._process_item(item_id))
                finalize_tick += 1
                if finalize_tick >= 5:
                    finalize_tick = 0
                    ready_batch_ids = await asyncio.to_thread(self._find_ready_batches)
                    if ready_batch_ids:
                        logger.info("发现待补偿最终化语音批次 batch_ids=%s", ready_batch_ids)
                    for batch_id in ready_batch_ids:
                        await asyncio.to_thread(self.finalize_batch, batch_id)
                cleanup_tick += 1
                if cleanup_tick >= 60:
                    cleanup_tick = 0
                    await asyncio.to_thread(self._cleanup_expired)
            except asyncio.CancelledError:
                break
            except Exception:
                logger.exception("语音转写调度循环异常")
            await asyncio.sleep(1)

    @staticmethod
    def _find_ready_batches() -> list[UUID]:
        db = SessionLocal()
        try:
            batches = db.query(TranscriptionBatch).filter(
                TranscriptionBatch.status.in_(("QUEUED", "PROCESSING", "FINALIZING")),
            ).all()
            return [
                batch.id for batch in batches
                if batch.items
                and all(item.status in {"SUCCEEDED", "DELETED"} for item in batch.items)
                and any(item.status == "SUCCEEDED" for item in batch.items)
            ]
        finally:
            db.close()

    @staticmethod
    def _claim_items(limit: int, excluded: set[UUID]) -> list[UUID]:
        db = SessionLocal()
        try:
            query = (
                db.query(TranscriptionItem)
                .join(TranscriptionBatch)
                .filter(
                    TranscriptionBatch.status.in_(ACTIVE_BATCH_STATUSES),
                    TranscriptionItem.status.in_(("QUEUED", "SUBMITTED", "RUNNING")),
                )
                .order_by(TranscriptionBatch.started_at, TranscriptionItem.sort_order, TranscriptionItem.created_at)
            )
            if excluded:
                query = query.filter(~TranscriptionItem.id.in_(excluded))
            items = query.with_for_update(skip_locked=True).limit(limit).all()
            for item in items:
                if item.status == "QUEUED":
                    item.status = "SUBMITTING"
                item.batch.status = "PROCESSING"
            db.commit()
            return [item.id for item in items]
        finally:
            db.close()

    async def _process_item(self, item_id: UUID) -> None:
        try:
            state = await asyncio.to_thread(self._load_item_state, item_id)
            if not state:
                logger.info("跳过语音项处理：状态已不可处理 item_id=%s", item_id)
                return
            provider_task_id, storage_key, user_id, batch_id, batch_vocabulary_id, batch_fingerprint = state
            logger.info("开始处理语音项 item_id=%s has_provider_task=%s has_file=%s", item_id, bool(provider_task_id), bool(storage_key))
            if not provider_task_id:
                if not storage_key:
                    raise FunAsrError("OBJECT_KEY_MISSING", "语音对象不存在，请重新上传")
                vocabulary_id = batch_vocabulary_id
                if batch_fingerprint is None:
                    vocabulary_id = await self._ensure_batch_vocabulary(batch_id, user_id)
                file_url = await asyncio.to_thread(
                    minio_storage_service.presigned_get_url,
                    storage_key,
                    timedelta(hours=settings.TRANSCRIPTION_DOWNLOAD_TOKEN_HOURS),
                )
                logger.info("提交语音项到 Fun-ASR item_id=%s file_url=%s", item_id, _mask_download_url(file_url))
                task = await fun_asr_service.submit(file_url, vocabulary_id=vocabulary_id)
                accepted = await asyncio.to_thread(
                    self._set_provider_task, item_id, task.task_id, task.request_id
                )
                if not accepted:
                    logger.info("跳过语音项处理：provider task 落库失败 item_id=%s task_id=%s", item_id, task.task_id)
                    return
                provider_task_id = task.task_id
                logger.info("语音项提交成功 item_id=%s provider_task_id=%s request_id=%s", item_id, provider_task_id, task.request_id)

            while not self._stopping:
                result = await fun_asr_service.query(provider_task_id)
                logger.info(
                    "语音项查询结果 item_id=%s provider_task_id=%s status=%s request_id=%s error_code=%s",
                    item_id,
                    provider_task_id,
                    result.status,
                    result.request_id,
                    result.error_code,
                )
                if result.status in {"PENDING", "RUNNING"}:
                    await asyncio.to_thread(
                        self._set_running_status,
                        item_id,
                        "RUNNING" if result.status == "RUNNING" else "SUBMITTED",
                        result.request_id,
                    )
                    await asyncio.sleep(3)
                    continue
                if result.status == "SUCCEEDED":
                    if not result.transcription_url:
                        raise FunAsrError("RESULT_URL_MISSING", "识别完成但未返回结果地址")
                    logger.info("语音项识别成功，开始下载结果 item_id=%s provider_task_id=%s", item_id, provider_task_id)
                    text = await fun_asr_service.fetch_transcript(result.transcription_url)
                    object_key = await asyncio.to_thread(self._complete_item, item_id, text, result.request_id)
                    logger.info("语音项完成 item_id=%s provider_task_id=%s transcript_length=%s", item_id, provider_task_id, len(text))
                    completed_key = object_key or storage_key
                    if await asyncio.to_thread(remove_file, completed_key):
                        await asyncio.to_thread(self._clear_storage_key, item_id, completed_key)
                        logger.info("语音项临时文件已删除 item_id=%s", item_id)
                    await asyncio.to_thread(self.evaluate_batch_for_item, item_id)
                    return
                raise FunAsrError(
                    result.error_code or "PROVIDER_FAILED",
                    result.error_message or "语音识别失败",
                )
        except asyncio.CancelledError:
            raise
        except FunAsrError as exc:
            logger.warning("语音项处理失败 item_id=%s code=%s message=%s", item_id, exc.code, str(exc))
            await asyncio.to_thread(self._fail_item, item_id, exc.code, str(exc))
            await asyncio.to_thread(self.evaluate_batch_for_item, item_id)
        except MinioStorageError as exc:
            logger.warning("语音项对象存储处理失败 item_id=%s message=%s", item_id, str(exc))
            await asyncio.to_thread(self._fail_item, item_id, "STORAGE_ERROR", str(exc))
            await asyncio.to_thread(self.evaluate_batch_for_item, item_id)
        except Exception:
            logger.exception("处理语音项失败 item_id=%s", item_id)
            await asyncio.to_thread(self._fail_item, item_id, "INTERNAL_ERROR", "语音处理异常，请重试")
            await asyncio.to_thread(self.evaluate_batch_for_item, item_id)

    @staticmethod
    def _load_item_state(item_id: UUID) -> tuple[str | None, str | None, UUID, UUID, str | None, str | None] | None:
        db = SessionLocal()
        try:
            item = db.query(TranscriptionItem).filter_by(id=item_id).first()
            if not item or item.batch.status not in ACTIVE_BATCH_STATUSES:
                return None
            return (
                item.provider_task_id,
                item.storage_key,
                item.batch.user_id,
                item.batch.id,
                item.batch.hotword_vocabulary_id,
                item.batch.hotword_fingerprint,
            )
        finally:
            db.close()

    async def _ensure_batch_vocabulary(self, batch_id: UUID, user_id: UUID) -> str | None:
        """批次首次提交前同步一次词表，批次内后续音频复用同一词表。"""
        async with self._vocabulary_lock:
            current = await asyncio.to_thread(self._load_batch_vocabulary_state, batch_id)
            if current and current[1] is not None:
                return current[0]
            vocabulary_id, fingerprint = await self._ensure_user_vocabulary(user_id)
            await asyncio.to_thread(self._set_batch_vocabulary, batch_id, vocabulary_id, fingerprint)
            return vocabulary_id

    async def _ensure_user_vocabulary(self, user_id: UUID) -> tuple[str | None, str]:
        """按用户级指纹检查并完整覆盖阿里云词表。"""
        entries, fingerprint, state = await asyncio.to_thread(self._load_vocabulary_inputs, user_id)
        target_model = await asyncio.to_thread(lambda: fun_asr_service.model_name)
        if state and state.fingerprint == fingerprint and state.target_model == target_model:
            return state.vocabulary_id, fingerprint

        if not entries:
            if state and state.vocabulary_id:
                try:
                    await fun_asr_service.delete_vocabulary(state.vocabulary_id)
                except FunAsrError:
                    logger.warning("清理空热词表失败 user_id=%s vocabulary_id=%s", user_id, state.vocabulary_id, exc_info=True)
            await asyncio.to_thread(self._persist_vocabulary_state, user_id, None, target_model, fingerprint)
            return None, fingerprint

        try:
            if state and state.vocabulary_id and state.target_model == target_model:
                await fun_asr_service.update_vocabulary(state.vocabulary_id, entries)
                vocabulary_id = state.vocabulary_id
            else:
                if state and state.vocabulary_id:
                    try:
                        await fun_asr_service.delete_vocabulary(state.vocabulary_id)
                    except FunAsrError:
                        logger.warning("清理旧热词表失败 user_id=%s vocabulary_id=%s", user_id, state.vocabulary_id, exc_info=True)
                vocabulary_id = await fun_asr_service.create_vocabulary(entries, f"d{user_id.hex[:9]}")
        except HotwordUnsupported as exc:
            logger.warning("当前 ASR 模型不支持热词，跳过热词 user_id=%s model=%s message=%s", user_id, target_model, exc)
            vocabulary_id = None

        await asyncio.to_thread(self._persist_vocabulary_state, user_id, vocabulary_id, target_model, fingerprint)
        return vocabulary_id, fingerprint

    @staticmethod
    def _load_vocabulary_inputs(user_id: UUID):
        db = SessionLocal()
        try:
            entries = build_hotword_entries(db, user_id)
            fingerprint = hotword_fingerprint(entries)
            state = load_vocabulary_state(db, user_id)
            return entries, fingerprint, state
        finally:
            db.close()

    @staticmethod
    def _load_batch_vocabulary_state(batch_id: UUID) -> tuple[str | None, str | None] | None:
        db = SessionLocal()
        try:
            batch = db.query(TranscriptionBatch).filter_by(id=batch_id).first()
            if not batch or batch.status not in ACTIVE_BATCH_STATUSES:
                return None
            return batch.hotword_vocabulary_id, batch.hotword_fingerprint
        finally:
            db.close()

    @staticmethod
    def _set_batch_vocabulary(batch_id: UUID, vocabulary_id: str | None, fingerprint: str) -> None:
        db = SessionLocal()
        try:
            batch = db.query(TranscriptionBatch).filter_by(id=batch_id).with_for_update().first()
            if not batch or batch.status not in ACTIVE_BATCH_STATUSES or batch.hotword_fingerprint is not None:
                return
            batch.hotword_vocabulary_id = vocabulary_id
            batch.hotword_fingerprint = fingerprint
            db.commit()
        finally:
            db.close()

    @staticmethod
    def _persist_vocabulary_state(
        user_id: UUID,
        vocabulary_id: str | None,
        target_model: str,
        fingerprint: str,
    ) -> None:
        db = SessionLocal()
        try:
            save_vocabulary_state(db, user_id, vocabulary_id, target_model, fingerprint)
        finally:
            db.close()

    @staticmethod
    def _set_provider_task(item_id: UUID, task_id: str, request_id: str | None) -> bool:
        db = SessionLocal()
        try:
            item = db.query(TranscriptionItem).filter_by(id=item_id).with_for_update().first()
            if not item or item.batch.status not in ACTIVE_BATCH_STATUSES:
                return False
            item.provider_task_id = task_id
            item.provider_request_id = request_id
            item.status = "SUBMITTED"
            db.commit()
            logger.info("语音项 provider task 已保存 item_id=%s provider_task_id=%s request_id=%s", item_id, task_id, request_id)
            return True
        finally:
            db.close()

    @staticmethod
    def _set_running_status(item_id: UUID, status: str, request_id: str | None) -> None:
        db = SessionLocal()
        try:
            item = db.query(TranscriptionItem).filter_by(id=item_id).first()
            if item and item.batch.status in ACTIVE_BATCH_STATUSES:
                old_status = item.status
                item.status = status
                item.provider_request_id = request_id or item.provider_request_id
                db.commit()
                if old_status != status:
                    logger.info("语音项状态更新 item_id=%s old_status=%s new_status=%s", item_id, old_status, status)
        finally:
            db.close()

    @staticmethod
    def _complete_item(item_id: UUID, text: str, request_id: str | None) -> str | None:
        db = SessionLocal()
        try:
            item = db.query(TranscriptionItem).filter_by(id=item_id).with_for_update().first()
            if not item or item.batch.status not in ACTIVE_BATCH_STATUSES:
                return None
            object_key = item.storage_key
            item.status = "SUCCEEDED"
            item.transcript_text = text
            item.provider_request_id = request_id or item.provider_request_id
            db.commit()
            logger.info("语音项识别结果已保存 item_id=%s transcript_length=%s", item_id, len(text))
            return object_key
        finally:
            db.close()

    @staticmethod
    def _clear_storage_key(item_id: UUID, expected_key: str | None) -> None:
        if not expected_key:
            return
        db = SessionLocal()
        try:
            item = db.query(TranscriptionItem).filter_by(id=item_id).first()
            if item and item.storage_key == expected_key:
                item.storage_key = None
                db.commit()
                logger.info("语音项 storage_key 已清空 item_id=%s", item_id)
        finally:
            db.close()

    @staticmethod
    def _fail_item(item_id: UUID, code: str, message: str) -> None:
        db = SessionLocal()
        try:
            item = db.query(TranscriptionItem).filter_by(id=item_id).with_for_update().first()
            if not item or item.batch.status not in ACTIVE_BATCH_STATUSES:
                return
            item.status = "FAILED"
            item.error_code = code
            item.error_message = message[:1000]
            db.commit()
            logger.info("语音项已标记失败 item_id=%s code=%s message=%s", item_id, code, message[:200])
        finally:
            db.close()

    def evaluate_batch_for_item(self, item_id: UUID) -> None:
        db = SessionLocal()
        try:
            item = db.query(TranscriptionItem).filter_by(id=item_id).first()
            if item:
                batch_id = item.batch_id
            else:
                return
        finally:
            db.close()
        self.evaluate_batch(batch_id)

    def evaluate_batch(self, batch_id: UUID) -> None:
        db = SessionLocal()
        should_finalize = False
        try:
            batch = db.query(TranscriptionBatch).filter_by(id=batch_id).with_for_update().first()
            if not batch or batch.status not in {"QUEUED", "PROCESSING", "PARTIAL_FAILED"}:
                return
            items = [item for item in batch.items if item.status != "DELETED"]
            if any(item.status in ACTIVE_ITEM_STATUSES for item in items):
                batch.status = "PROCESSING"
            elif any(item.status == "FAILED" for item in items):
                batch.status = "PARTIAL_FAILED"
                batch.expires_at = datetime.utcnow() + timedelta(days=settings.TRANSCRIPTION_FAILED_RETENTION_DAYS)
            elif any(item.status == "SUCCEEDED" for item in items):
                should_finalize = True
            else:
                batch.status = "CANCELLED"
                batch.base_text = None
                batch.completed_at = datetime.utcnow()
            db.commit()
            logger.info(
                "语音批次状态评估 batch_id=%s status=%s item_statuses=%s should_finalize=%s",
                batch.id,
                batch.status,
                {status: sum(1 for item in items if item.status == status) for status in sorted({item.status for item in items})},
                should_finalize,
            )
        finally:
            db.close()
        if should_finalize:
            self.finalize_batch(batch_id)

    @staticmethod
    def finalize_batch(batch_id: UUID) -> None:
        db = SessionLocal()
        try:
            batch = db.query(TranscriptionBatch).filter_by(id=batch_id).with_for_update().first()
            if not batch or batch.diary_id or batch.status not in {"QUEUED", "PROCESSING", "PARTIAL_FAILED", "FINALIZING"}:
                logger.info(
                    "跳过语音批次最终化 batch_id=%s exists=%s status=%s diary_id=%s",
                    batch_id,
                    bool(batch),
                    batch.status if batch else None,
                    batch.diary_id if batch else None,
                )
                return
            items = [item for item in batch.items if item.status != "DELETED"]
            if not items or any(item.status != "SUCCEEDED" for item in items):
                logger.info("跳过语音批次最终化：仍有未成功项 batch_id=%s item_count=%s", batch.id, len(items))
                return
            original_text = compose_transcription_text(batch.base_text, items)
            logger.info("开始最终化语音批次 batch_id=%s user_id=%s item_count=%s diary_date=%s", batch.id, batch.user_id, len(items), batch.diary_date)
            diary = batch.diary
            if diary is None:
                # 兼容新逻辑上线前已启动的批次。
                diary = Diary(
                    user_id=batch.user_id,
                    original_text=original_text,
                    diary_date=batch.diary_date,
                    status=DiaryStatus.saved,
                )
                db.add(diary)
                db.flush()
                batch.diary_id = diary.id
            elif diary.deleted_at is None:
                diary.original_text = original_text
                diary.diary_date = batch.diary_date
                diary.content_revision += 1
                diary.is_dirty = False
            batch.status = "COMPLETED"
            batch.completed_at = datetime.utcnow()
            batch.expires_at = None
            batch.base_text = None
            for item in items:
                item.transcript_text = None
            db.commit()
            logger.info("语音批次最终化完成 batch_id=%s diary_id=%s text_length=%s", batch.id, diary.id, len(diary.original_text or ""))
        except Exception:
            db.rollback()
            logger.exception("自动创建日记失败 batch_id=%s", batch_id)
        finally:
            db.close()

    def _recover_interrupted(self) -> None:
        db = SessionLocal()
        affected: list[UUID] = []
        try:
            items = db.query(TranscriptionItem).filter(TranscriptionItem.status == "SUBMITTING").all()
            for item in items:
                item.status = "FAILED"
                item.error_code = "SUBMIT_RESULT_UNKNOWN"
                item.error_message = "服务重启时提交结果未知，请手动重试"
                affected.append(item.batch_id)
            batches = db.query(TranscriptionBatch).filter(TranscriptionBatch.status == "FINALIZING").all()
            for batch in batches:
                if batch.diary_id:
                    batch.status = "COMPLETED"
                else:
                    batch.status = "PROCESSING"
                    affected.append(batch.id)
            db.commit()
            if affected:
                logger.info("语音转写重启恢复 affected_batch_ids=%s", sorted(set(affected), key=str))
        finally:
            db.close()
        for batch_id in set(affected):
            self.evaluate_batch(batch_id)

    @staticmethod
    def _cleanup_expired() -> None:
        now = datetime.utcnow()
        db = SessionLocal()
        object_keys: list[str] = []
        residual_files: list[tuple[UUID, str]] = []
        try:
            collecting = db.query(TranscriptionBatch).filter(
                TranscriptionBatch.status == "COLLECTING",
                TranscriptionBatch.created_at < now - timedelta(hours=24),
            ).all()
            for batch in collecting:
                object_keys.extend(item.storage_key for item in batch.items if item.storage_key)
                db.delete(batch)
            expired = db.query(TranscriptionBatch).filter(
                TranscriptionBatch.status == "PARTIAL_FAILED",
                TranscriptionBatch.expires_at <= now,
            ).all()
            for batch in expired:
                object_keys.extend(item.storage_key for item in batch.items if item.storage_key)
                batch.status = "EXPIRED"
                batch.base_text = None
                batch.completed_at = now
                for item in batch.items:
                    item.transcript_text = None
            terminal_cutoff = now - timedelta(days=30)
            residuals = db.query(TranscriptionItem).join(TranscriptionBatch).filter(
                TranscriptionItem.storage_key.is_not(None),
                (
                    (TranscriptionItem.status == "SUCCEEDED")
                    | TranscriptionBatch.status.in_(("COMPLETED", "CANCELLED", "EXPIRED"))
                ),
            ).all()
            residual_files = [(item.id, item.storage_key) for item in residuals if item.storage_key]
            terminal = db.query(TranscriptionBatch).filter(
                TranscriptionBatch.status.in_(("COMPLETED", "CANCELLED", "EXPIRED")),
                TranscriptionBatch.completed_at < terminal_cutoff,
            ).all()
            for batch in terminal:
                object_keys.extend(item.storage_key for item in batch.items if item.storage_key)
                db.delete(batch)
            db.commit()
            if collecting or expired or terminal or residual_files:
                logger.info(
                    "语音转写清理完成 collecting=%s expired=%s terminal=%s residual_files=%s removed_paths=%s",
                    len(collecting),
                    len(expired),
                    len(terminal),
                    len(residual_files),
                    len(object_keys),
                )
        finally:
            db.close()
        for object_key in object_keys:
            remove_file(object_key)
        for item_id, object_key in residual_files:
            if remove_file(object_key):
                TranscriptionTaskManager._clear_storage_key(item_id, object_key)


transcription_task_manager = TranscriptionTaskManager()
