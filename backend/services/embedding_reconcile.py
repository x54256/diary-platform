"""事件 embedding 向量定时对账调度器。

周期性扫描「有检索内容（search_text 非空）但缺少语义分块」的事件，补算其 embedding，
补偿增量同步（organize/analyze/更新事件/更新整理）中因 API 异常 / 配置缺失而漏算的事件
（决策 11，比设计默认更强）。收敛性同回填脚本：仅补算有内容却无 chunk 的事件，写入后不再选中。

要求应用以单 worker 运行（与 BackupScheduler 一致）。
"""

import asyncio
import logging
import os
from typing import List, Optional

from database import SessionLocal, engine
from sqlalchemy import text

from services.embedding_sync import sync_event_embeddings

logger = logging.getLogger("app.embedding_reconcile")

# 对账间隔（秒），可用环境变量覆盖。默认 6 小时。
RECONCILE_INTERVAL_SECONDS = int(os.getenv("EMBEDDING_RECONCILE_INTERVAL_SECONDS", "21600"))
# 单次扫描批量上限。
RECONCILE_BATCH_SIZE = int(os.getenv("EMBEDDING_RECONCILE_BATCH_SIZE", "200"))


def _find_missing_event_ids(limit: int) -> List:
    """返回有 search_text 但无语义分块的事件 ID 列表。"""
    with engine.connect() as conn:
        rows = conn.execute(
            text(
                """
                SELECT de.id FROM diary_events de
                LEFT JOIN event_embedding_chunks eec ON eec.event_id = de.id
                WHERE eec.id IS NULL AND de.search_text IS NOT NULL AND de.search_text <> ''
                ORDER BY de.updated_at
                LIMIT :lim
                """
            ),
            {"lim": limit},
        ).fetchall()
    return [row[0] for row in rows]


def reconcile_once() -> int:
    """执行一次对账：补算缺失语义分块的事件。返回本次处理事件数。"""
    event_ids = _find_missing_event_ids(RECONCILE_BATCH_SIZE)
    if not event_ids:
        return 0
    db = SessionLocal()
    processed = 0
    try:
        for event_id in event_ids:
            try:
                sync_event_embeddings(db, event_id)
                db.commit()
                processed += 1
            except Exception as exc:  # noqa: BLE001
                db.rollback()
                logger.warning("对账补算失败 event_id=%s：%s", event_id, exc)
        return processed
    finally:
        db.close()


class EmbeddingReconcileScheduler:
    """事件 embedding 定时对账调度器（镜像 BackupScheduler 模式）。"""

    def __init__(self, interval_seconds: int = RECONCILE_INTERVAL_SECONDS) -> None:
        self._interval = interval_seconds
        self._runner: Optional[asyncio.Task] = None
        self._stopping = False

    async def start(self) -> None:
        if self._runner and not self._runner.done():
            return
        self._stopping = False
        self._runner = asyncio.create_task(self._run(), name="embedding-reconcile")
        logger.info("事件 embedding 对账调度器已启动，间隔=%s 秒", self._interval)

    async def stop(self) -> None:
        self._stopping = True
        if self._runner:
            self._runner.cancel()
            await asyncio.gather(self._runner, return_exceptions=True)
        logger.info("事件 embedding 对账调度器已停止")

    async def _run(self) -> None:
        while not self._stopping:
            try:
                processed = await asyncio.to_thread(reconcile_once)
                if processed:
                    logger.info("事件 embedding 对账完成，本次补算 %d 个事件", processed)
            except Exception as exc:  # noqa: BLE001
                logger.exception("事件 embedding 对账异常：%s", exc)
            # 固定间隔休眠；停止信号在休眠后检查。
            await asyncio.sleep(self._interval)


embedding_reconcile_scheduler = EmbeddingReconcileScheduler()
