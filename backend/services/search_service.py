"""统一搜索服务：跨表检索事件内容（含关联分析），按相关度排序、去重、分页。

检索范围（仅事件）：
- 事件自身字段：event_title / body / feeling / reflection
- 关联分析内容：analysis_items（scope=EVENT，覆盖全部 7 种类型）的 content / question

语义增强（增量）：
- 在关键词 pg_trgm 分支之外，叠加 embedding 语义分支（event_embedding_chunks）。
- 支持 mode：keyword（仅关键词）/ semantic（仅语义）/ hybrid（RRF k=60 融合，默认）。
- hybrid 下若语义分支不可用（未配置 / API 异常 / 无 pgvector），自动降级为关键词召回，
  保证搜索可用性（fail-open）。
- 查询 embedding 走进程内 TTL 缓存（services.embedding_cache），降低出网与耗时。
- 命中语义分块的层经 matched_chunk_types 随结果回传，供前端高亮。

不检索 event_tags（标签仅展示）、diary_organized 的 title/summary/content、diaries.original_text。
检索产物 diary_events.search_text 由触发器（迁移 036）维护，关键词分支只做查询与组装。
"""

from datetime import date
from typing import Any, List, Optional, Tuple

from sqlalchemy import func
from sqlalchemy.orm import Session

from models.diary import (
    AnalysisRun,
    Diary,
    DiaryEvent,
    DiaryOrganized,
    DiaryStatus,
    EventEmbeddingChunk,
)
from services.analysis_history import get_current_analysis_run

# RRF 融合常数 k（决策 12：锁死为 60）。
RRF_K = 60

# 搜索服务默认模式：hybrid（RRF k=60 融合关键词 + 语义；决策 9 锁死）。
# 与 API 层（routers.diaries.search_diaries）默认 hybrid 保持一致，避免任何不带
# mode 直接调用 search_events 的代码静默退化为纯关键词。语义分支不可用时由
# _hybrid_mode 自动 fail-open 降级关键词，因此 hybrid 默认值对关键词场景安全。
DEFAULT_SEARCH_MODE = "hybrid"

# 单次语义召回考虑的最大候选事件数（性能上限保护）。
SEMANTIC_CANDIDATE_CAP = 200


def _embed_query(q: str) -> Optional[List[float]]:
    """获取查询文本的 embedding 向量（优先进程内缓存）。失败抛错由调用方处理。"""
    from services.embedding_cache import cache_query_embedding, get_cached_query_embedding
    from services.embedding_client import embed_texts

    cached = get_cached_query_embedding(q)
    if cached is not None:
        return cached
    vectors = embed_texts([q])
    vec = vectors[0] if vectors else None
    if vec is not None:
        cache_query_embedding(q, vec)
    return vec


def _escape_like(text: str) -> str:
    """转义 LIKE 通配符，避免用户输入的 % / _ 被当作通配符导致错误超匹配。"""
    return text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _base_filters(user_id: Any, start_date: Optional[date], end_date: Optional[date]) -> List[Any]:
    """关键词 / 语义分支共用的隔离过滤：user_id + 软删除 + 状态 + 日期。"""
    filters: List[Any] = [
        Diary.user_id == user_id,
        Diary.deleted_at.is_(None),
        Diary.status.in_([DiaryStatus.organized.value, DiaryStatus.analyzed.value]),
    ]
    if start_date is not None:
        filters.append(Diary.diary_date >= start_date)
    if end_date is not None:
        filters.append(Diary.diary_date <= end_date)
    return filters


def _keyword_candidates(
    db: Session,
    user_id: Any,
    q: str,
    start_date: Optional[date],
    end_date: Optional[date],
) -> List[Tuple[Any, Any, date]]:
    """关键词分支候选：返回 [(event_id, diary_id, diary_date)] 按 similarity 降序（全量，未分页）。"""
    escaped = _escape_like(q)
    search_term = f"%{escaped}%"
    similarity_expr = func.similarity(DiaryEvent.search_text, q)
    rows = (
        db.query(
            DiaryEvent.id,
            Diary.id.label("diary_id"),
            Diary.diary_date,
        )
        .join(DiaryOrganized, DiaryOrganized.id == DiaryEvent.diary_organized_id)
        .join(Diary, Diary.id == DiaryOrganized.diary_id)
        .filter(
            DiaryEvent.search_text.isnot(None),
            DiaryEvent.search_text.ilike(search_term, escape="\\"),
            *_base_filters(user_id, start_date, end_date),
        )
        .order_by(similarity_expr.desc(), Diary.diary_date.desc())
        .all()
    )
    return [(row.id, row.diary_id, row.diary_date) for row in rows]


def _semantic_candidates(
    db: Session,
    user_id: Any,
    q: str,
    start_date: Optional[date],
    end_date: Optional[date],
) -> Tuple[List[Tuple[Any, Any, date]], dict]:
    """语义分支候选：查询 embedding 余弦最近邻，返回 (有序候选, 命中层映射)。

    Returns:
        (candidates, chunk_types_by_event_id)
        - candidates: [(event_id, diary_id, diary_date)] 按余弦距离升序（最相似在前）。
        - chunk_types_by_event_id: {event_id: set(chunk_type)}，记录每个事件命中了哪些语义层。

    Note:
        查询 embedding 为空（空文本）或无任何分块时返回 ([], {})。
    """
    query_vec = _embed_query(q)
    if query_vec is None:
        return [], {}

    distance_expr = EventEmbeddingChunk.embedding.cosine_distance(query_vec)
    rows = (
        db.query(
            EventEmbeddingChunk.event_id,
            Diary.id.label("diary_id"),
            Diary.diary_date,
            EventEmbeddingChunk.chunk_type,
            distance_expr.label("dist"),
        )
        .join(DiaryEvent, DiaryEvent.id == EventEmbeddingChunk.event_id)
        .join(DiaryOrganized, DiaryOrganized.id == DiaryEvent.diary_organized_id)
        .join(Diary, Diary.id == DiaryOrganized.diary_id)
        .filter(*_base_filters(user_id, start_date, end_date))
        .order_by(distance_expr.asc())
        .all()
    )

    # 同一事件可能命中多个 chunk：取最小距离（最相似），并汇总命中层。
    best_dist: dict = {}
    event_meta: dict = {}
    chunk_types: dict = {}
    for row in rows:
        event_id = row.event_id
        event_meta[event_id] = (row.diary_id, row.diary_date)
        if event_id not in best_dist or row.dist < best_dist[event_id]:
            best_dist[event_id] = row.dist
        chunk_types.setdefault(event_id, set()).add(row.chunk_type)

    ordered = sorted(best_dist.keys(), key=lambda eid: best_dist[eid])
    # 性能上限保护：仅保留最近邻 Top N 参与融合。
    ordered = ordered[:SEMANTIC_CANDIDATE_CAP]
    candidates = [(eid, event_meta[eid][0], event_meta[eid][1]) for eid in ordered]
    return candidates, chunk_types


def _rrf_fuse(
    keyword_list: List[Tuple[Any, Any, date]],
    semantic_list: List[Tuple[Any, Any, date]],
    k: int = RRF_K,
) -> Tuple[List[Any], dict]:
    """RRF 融合两个分支的命中列表。

    RRF 分数 = Σ 1/(k + rank)，rank 为各分支内 1 基名次（按相关度顺序）。
    语义分支不可用时（semantic_list 为空），结果退化为关键词排序。

    Returns:
        (fused_event_ids, meta_by_id) 其中 meta_by_id: {event_id: (diary_id, diary_date)}。
    """
    scores: dict = {}
    meta: dict = {}
    for rank, row in enumerate(keyword_list, start=1):
        event_id = row[0]
        scores[event_id] = scores.get(event_id, 0.0) + 1.0 / (k + rank)
        meta[event_id] = (row[1], row[2])
    for rank, row in enumerate(semantic_list, start=1):
        event_id = row[0]
        scores[event_id] = scores.get(event_id, 0.0) + 1.0 / (k + rank)
        if event_id not in meta:
            meta[event_id] = (row[1], row[2])
    fused = sorted(scores.keys(), key=lambda eid: scores[eid], reverse=True)
    return fused, meta


def _build_event_items(
    db: Session,
    event_ids: List[Any],
    user_id: Any,
    chunk_types_by_id: Optional[dict],
    meta_by_id: dict,
) -> List[dict]:
    """按 event_ids 顺序序列化事件卡，并附加检索附加字段与 matched_chunk_types。"""
    # 延迟导入：routers.diaries 在模块顶层导入了本模块，顶层导入会形成环形依赖。
    from routers.diaries import serialize_event

    if not event_ids:
        return []

    events = db.query(DiaryEvent).filter(DiaryEvent.id.in_(event_ids)).all()
    events_by_id = {event.id: event for event in events}

    # diary_id 优先取自候选元数据（已在 JOIN 中计算），避免逐个触发关系加载。
    diary_ids = list({meta[0] for meta in meta_by_id.values() if meta and meta[0] is not None})
    current_runs: dict = {}
    for diary_id in diary_ids:
        current_runs[diary_id] = get_current_analysis_run(db, diary_id)

    chunk_types_by_id = chunk_types_by_id or {}
    items: List[dict] = []
    for event_id in event_ids:
        event = events_by_id.get(event_id)
        if event is None:
            continue
        meta = meta_by_id.get(event_id)
        # diary_id 优先取候选元数据（已 join 计算），否则回退到关系属性。
        diary_id = meta[0] if (meta and meta[0] is not None) else (
            event.organized.diary_id if event.organized else None
        )
        current_run: Optional[AnalysisRun] = current_runs.get(diary_id) if diary_id else None
        data = serialize_event(event, current_run, user_id, db)
        data["diary_id"] = diary_id
        # diary_date 优先取候选元数据（已 join 计算），避免额外查询；否则回退到关系属性。
        if meta is not None and meta[1] is not None:
            data["diary_date"] = meta[1]
        elif event.organized is not None and event.organized.diary is not None:
            data["diary_date"] = event.organized.diary.diary_date
        else:
            data["diary_date"] = None
        data["rank"] = 0.0
        data["analysis_run_id"] = current_run.id if current_run else None
        data["matched_chunk_types"] = sorted(chunk_types_by_id.get(event_id, set()))
        items.append(data)
    return items


def _keyword_mode(
    db: Session,
    user_id: Any,
    q: str,
    start_date: Optional[date],
    end_date: Optional[date],
    limit: int,
    offset: int,
) -> Tuple[list, int]:
    candidates = _keyword_candidates(db, user_id, q, start_date, end_date)
    total = len(candidates)
    page = candidates[offset : offset + limit]
    meta = {row[0]: (row[1], row[2]) for row in page}
    items = _build_event_items(db, [row[0] for row in page], user_id, {}, meta)
    return items, total


def _semantic_mode(
    db: Session,
    user_id: Any,
    q: str,
    start_date: Optional[date],
    end_date: Optional[date],
    limit: int,
    offset: int,
) -> Tuple[list, int]:
    candidates, chunk_types = _semantic_candidates(db, user_id, q, start_date, end_date)
    total = len(candidates)
    page = candidates[offset : offset + limit]
    meta = {row[0]: (row[1], row[2]) for row in page}
    items = _build_event_items(db, [row[0] for row in page], user_id, chunk_types, meta)
    return items, total


def _hybrid_mode(
    db: Session,
    user_id: Any,
    q: str,
    start_date: Optional[date],
    end_date: Optional[date],
    limit: int,
    offset: int,
) -> Tuple[list, int]:
    import logging

    logger = logging.getLogger(__name__)
    keyword_list = _keyword_candidates(db, user_id, q, start_date, end_date)
    try:
        semantic_list, semantic_chunks = _semantic_candidates(db, user_id, q, start_date, end_date)
    except Exception as exc:  # noqa: BLE001
        # 语义分支不可用（未配置 / API 异常 / 无 pgvector）：降级为关键词召回。
        logger.warning("语义召回失败，降级为关键词召回：%s", exc)
        semantic_list, semantic_chunks = [], {}

    fused_ids, meta = _rrf_fuse(keyword_list, semantic_list)
    total = len(fused_ids)
    page = fused_ids[offset : offset + limit]
    page_meta = {eid: meta[eid] for eid in page}
    items = _build_event_items(db, page, user_id, semantic_chunks, page_meta)
    return items, total


def search_events(
    db: Session,
    user_id: Any,
    q: str,
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    limit: int = 20,
    offset: int = 0,
    mode: str = DEFAULT_SEARCH_MODE,
) -> Tuple[list, int]:
    """统一搜索事件。

    Args:
        db: 数据库会话。
        user_id: 当前用户 ID（来自 get_current_user，绝不使用客户端传入）。
        q: 查询文本（关键词子串匹配 / 语义向量召回共用）。
        start_date: 起始日期（基于所属 diary.diary_date），可选。
        end_date: 结束日期，可选。
        limit: 每页数量。
        offset: 偏移量。
        mode: 检索模式 "keyword" / "semantic" / "hybrid"（默认 keyword，API 层覆盖为 hybrid）。

    Returns:
        (items, total)：items 为序列化后的事件字典列表（追加 diary_id / diary_date /
        rank / analysis_run_id / matched_chunk_types），total 为命中事件精确计数。
    """
    query_text = (q or "").strip()
    if not query_text:
        return [], 0

    if mode == "semantic":
        return _semantic_mode(db, user_id, query_text, start_date, end_date, limit, offset)
    if mode == "hybrid":
        return _hybrid_mode(db, user_id, query_text, start_date, end_date, limit, offset)
    # 默认 / keyword
    return _keyword_mode(db, user_id, query_text, start_date, end_date, limit, offset)
