"""事件 embedding 向量增量同步。

职责：
- sync_event_embeddings：为单个事件（重新）计算三层分块（fact / self_understanding /
  cognition）embedding 并 upsert 到 event_embedding_chunks。
- enqueue_event_embedding_sync：在后台异步触发单个事件的同步（复用既有 asyncio.create_task
  后台任务模式；决策 7：无 Celery）。同步请求处理线程中无运行事件循环时，退化为独立守护线程，
  同样不阻塞 worker。

调用点（决策 5/7）：整理（organize）产出新事件、分析（analyze）产出认知层、更新事件、
更新整理内容——提交后各触发一次同步，保证语义向量与分析口径一致。
"""

import asyncio
import logging
import threading
from datetime import datetime
from typing import Iterable, List, Optional

from sqlalchemy.orm import Session

from database import SessionLocal
from models.diary import EventEmbeddingChunk
from services.embedding_client import EmbeddingClientError, embed_texts
from services.event_chunk_builder import (
    CHUNK_TYPE_COGNITION,
    CHUNK_TYPE_FACT,
    CHUNK_TYPE_SELF_UNDERSTANDING,
    build_event_chunk_contents,
)

logger = logging.getLogger(__name__)

# 三层语义分块固定顺序：fact / self_understanding / cognition。
CHUNK_TYPES_ORDER: tuple[str, ...] = (
    CHUNK_TYPE_FACT,
    CHUNK_TYPE_SELF_UNDERSTANDING,
    CHUNK_TYPE_COGNITION,
)


def _upsert_chunk(
    db: Session,
    event_id: object,
    chunk_type: str,
    text: str,
    vec: List[float],
) -> None:
    """对单个 (event_id, chunk_type) 做 upsert（存在则更新 content/embedding，否则插入）。"""
    existing = (
        db.query(EventEmbeddingChunk)
        .filter(
            EventEmbeddingChunk.event_id == event_id,
            EventEmbeddingChunk.chunk_type == chunk_type,
        )
        .first()
    )
    if existing is not None:
        existing.content = text
        existing.embedding = vec
        existing.updated_at = datetime.utcnow()
    else:
        db.add(
            EventEmbeddingChunk(
                event_id=event_id,
                chunk_type=chunk_type,
                content=text,
                embedding=vec,
            )
        )


def sync_event_embeddings(db: Session, event_id: object) -> int:
    """为单个事件（重新）计算三层分块 embedding 并 upsert。

    Args:
        db: 数据库会话（调用方负责提交 / 回滚）。
        event_id: 目标事件 ID。

    Returns:
        成功写入的分块数（空文本分块跳过；embedding 调用失败抛 EmbeddingClientError）。
    """
    contents = build_event_chunk_contents(db, event_id)
    if not contents:
        return 0

    types: List[str] = [ct for ct in CHUNK_TYPES_ORDER if ct in contents]
    texts: List[str] = [contents[ct] for ct in types]
    if not texts:
        return 0

    vectors = embed_texts(texts)
    written = 0
    for chunk_type, text, vec in zip(types, texts, vectors):
        if vec is None:
            logger.warning(
                "分块 embedding 为空，跳过 event_id=%s chunk_type=%s", event_id, chunk_type
            )
            continue
        _upsert_chunk(db, event_id, chunk_type, text, vec)
        written += 1
    db.flush()
    return written


def _run_event_embedding_sync_blocking(event_id: str) -> None:
    """同步阻塞执行单个事件 embedding 同步（自带会话，供线程 / 协程复用）。"""
    db = SessionLocal()
    try:
        sync_event_embeddings(db, event_id)
        db.commit()
    except EmbeddingClientError as exc:
        logger.warning("事件 embedding 同步跳过（配置/调用问题）event_id=%s：%s", event_id, exc)
        db.rollback()
    except Exception as exc:  # noqa: BLE001
        logger.exception("事件 embedding 同步失败 event_id=%s", event_id)
        db.rollback()
    finally:
        db.close()


async def _run_event_embedding_sync(event_id: str) -> None:
    """后台协程：在独立线程执行同步，避免阻塞事件循环。"""
    await asyncio.to_thread(_run_event_embedding_sync_blocking, event_id)


def enqueue_event_embedding_sync(event_id: object) -> None:
    """在后台异步同步单个事件的 embedding。

    优先复用运行中的事件循环（asyncio.create_task，与 organize/analyze 后台任务一致）；
    无运行循环（如同步请求处理线程、离线脚本）则退化为独立守护线程，均不阻塞调用方。
    """
    event_id_str = str(event_id)
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    if loop is not None:
        asyncio.create_task(_run_event_embedding_sync(event_id_str), name=f"embed-{event_id_str}")
        return

    threading.Thread(
        target=_run_event_embedding_sync_blocking,
        args=(event_id_str,),
        daemon=True,
        name=f"embed-sync-{event_id_str}",
    ).start()


def enqueue_event_embedding_sync_many(event_ids: Iterable[object]) -> None:
    """批量入队多个事件的 embedding 同步（保持顺序无关，逐个调度）。"""
    for event_id in event_ids:
        if event_id is not None:
            enqueue_event_embedding_sync(event_id)
