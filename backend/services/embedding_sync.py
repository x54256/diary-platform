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
import hashlib
import logging
import threading
from datetime import datetime
from typing import Iterable, List, Optional

from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from database import SessionLocal
from models.diary import EventEmbeddingChunk, SearchSemanticIndexState
from services.embedding_client import EmbeddingClientError, embed_texts
from services.event_chunk_builder import (
    CHUNK_TYPE_COGNITION,
    CHUNK_TYPE_EVENT_CONTENT,
    CHUNK_TYPE_SELF_UNDERSTANDING,
    build_event_chunk_contents,
)

logger = logging.getLogger(__name__)

# 三层语义分块固定顺序。
CHUNK_TYPES_ORDER: tuple[str, ...] = (
    CHUNK_TYPE_EVENT_CONTENT,
    CHUNK_TYPE_SELF_UNDERSTANDING,
    CHUNK_TYPE_COGNITION,
)


def _upsert_chunk(
    db: Session,
    event_id: object,
    chunk_type: str,
    text: str,
    vec: List[float],
    analysis_run_id: Optional[object],
) -> None:
    """对单个 (event_id, chunk_type) 做 upsert。

    采用 PostgreSQL ``INSERT ... ON CONFLICT (event_id, chunk_type) DO UPDATE``
    （设计 §3.5/§3.7 要求），相较 select-then-upsert：
    - 省去命中时的额外 SELECT（单事件最多 3 次）；
    - 消除并发同步同一事件时的唯一约束竞态（原实现在并发下可能抛 IntegrityError
      被吞、导致分块漏写，需对账兜底）；冲突时仅更新 content/embedding/updated_at，
    created_at 由服务端默认值保留。
    """
    now = datetime.utcnow()
    stmt = pg_insert(EventEmbeddingChunk).values(
        event_id=event_id,
        analysis_run_id=analysis_run_id,
        chunk_type=chunk_type,
        content=text,
        embedding=vec,
        updated_at=now,
    ).on_conflict_do_update(
        index_elements=["event_id", "chunk_type"],
        set_={
            "content": text,
            "embedding": vec,
            "analysis_run_id": analysis_run_id,
            "updated_at": now,
        },
    )
    db.execute(stmt)


def sync_event_embeddings(db: Session, event_id: object) -> int:
    """为单个事件（重新）计算三层分块 embedding 并 upsert。

    Args:
        db: 数据库会话（调用方负责提交 / 回滚）。
        event_id: 目标事件 ID。

    Returns:
        成功写入的分块数（空文本分块跳过；embedding 调用失败抛 EmbeddingClientError）。
    """
    from models.diary import DiaryEvent
    from services.analysis_history import get_current_analysis_run

    event = db.get(DiaryEvent, event_id)
    if event is None or event.organized is None:
        return 0
    states = {
        state.chunk_type: state
        for state in db.query(SearchSemanticIndexState)
        .filter(SearchSemanticIndexState.event_id == event_id)
        .all()
    }
    analysis_state_ids = {state.analysis_run_id for chunk_type, state in states.items() if chunk_type != CHUNK_TYPE_EVENT_CONTENT}
    # 同一事件的分析层必须来自同一轮次；异常混合状态不能安全写入。
    if len(analysis_state_ids) > 1:
        logger.warning("embedding 索引状态轮次不一致，丢弃本次同步 event_id=%s", event_id)
        return 0
    source_run_id = next(iter(analysis_state_ids), None)
    # 只对 enqueue 时捕获的那一版内容生成向量。
    contents = build_event_chunk_contents(db, event_id, source_run_id)
    if not contents:
        return 0

    types: List[str] = [ct for ct in CHUNK_TYPES_ORDER if ct in contents]
    texts: List[str] = [contents[ct] for ct in types]
    if not texts:
        return 0

    snapshots = {
        chunk_type: (state.analysis_run_id, state.content_hash)
        for chunk_type, state in states.items() if chunk_type in contents
    }
    vectors = embed_texts(texts)
    written = 0
    # 网络调用期间可能发生事件编辑或 CURRENT 轮次切换。写入前重建当前版本，
    # 只有状态行、内容指纹和轮次三者仍完全一致时，才允许把 PENDING 置 READY。
    db.expire_all()
    event = db.get(DiaryEvent, event_id)
    current_run = get_current_analysis_run(db, event.organized.diary_id) if event and event.organized else None
    current_contents = build_event_chunk_contents(db, event_id, current_run.id if current_run else None)
    for chunk_type, text, vec in zip(types, texts, vectors):
        if vec is None:
            logger.warning(
                "分块 embedding 为空，跳过 event_id=%s chunk_type=%s", event_id, chunk_type
            )
            continue
        analysis_run_id = None if chunk_type == CHUNK_TYPE_EVENT_CONTENT else (current_run.id if current_run else None)
        state = (
            db.query(SearchSemanticIndexState)
            .filter(SearchSemanticIndexState.event_id == event_id, SearchSemanticIndexState.chunk_type == chunk_type)
            .one_or_none()
        )
        expected_hash = hashlib.sha256((current_contents.get(chunk_type) or "").encode("utf-8")).hexdigest()
        snapshot = snapshots.get(chunk_type)
        if (
            state is None
            or snapshot is None
            or state.status != "PENDING"
            or (state.analysis_run_id, state.content_hash) != snapshot
            or state.analysis_run_id != analysis_run_id
            or state.content_hash != expected_hash
            or expected_hash != hashlib.sha256(text.encode("utf-8")).hexdigest()
        ):
            logger.info("embedding 源版本已变化，丢弃旧向量 event_id=%s chunk_type=%s", event_id, chunk_type)
            continue
        _upsert_chunk(db, event_id, chunk_type, text, vec, analysis_run_id)
        state.status = "READY"
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


def _prepare_event_search_indexes_blocking(event_id: str) -> bool:
    """提交关键词片段与 PENDING 状态，绝不做历史扫描。"""
    from services.search_indexing import refresh_event_search_indexes

    db = SessionLocal()
    try:
        refresh_event_search_indexes(db, event_id)
        db.commit()
        return True
    except Exception:  # noqa: BLE001
        logger.exception("事件搜索索引准备失败 event_id=%s", event_id)
        db.rollback()
        return False
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
    # 关键词必须先落库；同时将每一层置 PENDING，从而阻止旧向量被查询。
    # 本函数只由新建/更新事件的业务调用，绝不扫描或补齐历史事件。
    if not _prepare_event_search_indexes_blocking(event_id_str):
        return
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
