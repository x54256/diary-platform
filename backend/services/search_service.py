"""破坏性日记级混合搜索。

关键词来自可展示的片段；语义来自三层向量。两条链路均在 SQL 中按用户、日记日期
和 CURRENT 分析轮次过滤。结果先以事件召回，再取每篇日记的最佳事件分进行日记级 RRF。
"""

import logging
import os
from collections import defaultdict
from datetime import date
from typing import Any, Optional

from sqlalchemy import and_, func, or_
from sqlalchemy.orm import Session, aliased

from models.diary import (
    AnalysisRun,
    Diary,
    DiaryEvent,
    DiaryOrganized,
    DiaryStatus,
    EventEmbeddingChunk,
    SearchKeywordSegment,
    SearchSemanticIndexState,
)

RRF_K = 60
SEMANTIC_CANDIDATE_CAP = 200
SEMANTIC_CHUNK_FETCH_LIMIT = 600
SEMANTIC_MIN_SIMILARITY = float(os.getenv("SEARCH_SEMANTIC_MIN_SIMILARITY", "0.35"))
logger = logging.getLogger(__name__)


def _embed_query(q: str) -> Optional[list[float]]:
    from services.embedding_cache import cache_query_embedding, get_cached_query_embedding
    from services.embedding_client import embed_texts

    cached = get_cached_query_embedding(q)
    if cached is not None:
        return cached
    vectors = embed_texts([q])
    vector = vectors[0] if vectors else None
    if vector is not None:
        cache_query_embedding(q, vector)
    return vector


def _escape_like(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _base_filters(user_id: Any, start_date: Optional[date], end_date: Optional[date]) -> list[Any]:
    filters: list[Any] = [
        Diary.user_id == user_id,
        Diary.deleted_at.is_(None),
        Diary.status.in_([DiaryStatus.organized.value, DiaryStatus.analyzed.value]),
    ]
    if start_date:
        filters.append(Diary.diary_date >= start_date)
    if end_date:
        filters.append(Diary.diary_date <= end_date)
    return filters


def _snippet(content: str, query: Optional[str] = None, radius: int = 70) -> str:
    """截取命中前后文；不产出 HTML，前端安全地完成红色高亮。"""
    text = " ".join((content or "").split())
    if not text:
        return ""
    pos = text.lower().find(query.lower()) if query else -1
    if pos < 0:
        return text[: radius * 2] + ("…" if len(text) > radius * 2 else "")
    start = max(0, pos - radius)
    end = min(len(text), pos + len(query or "") + radius)
    return ("…" if start else "") + text[start:end] + ("…" if end < len(text) else "")


def _current_analysis_filter(segment_run_id: Any, run_status: Any) -> Any:
    return or_(segment_run_id.is_(None), run_status == "CURRENT")


def _keyword_events(db: Session, user_id: Any, q: str, start_date: Optional[date], end_date: Optional[date]) -> dict:
    run = aliased(AnalysisRun)
    score = func.similarity(SearchKeywordSegment.content, q)
    rows = (
        db.query(
            SearchKeywordSegment.event_id,
            SearchKeywordSegment.diary_id,
            SearchKeywordSegment.analysis_run_id,
            SearchKeywordSegment.kind,
            SearchKeywordSegment.content,
            Diary.diary_date,
            score.label("score"),
        )
        .join(Diary, Diary.id == SearchKeywordSegment.diary_id)
        .outerjoin(run, run.id == SearchKeywordSegment.analysis_run_id)
        .filter(
            SearchKeywordSegment.content.ilike(f"%{_escape_like(q)}%", escape="\\"),
            _current_analysis_filter(SearchKeywordSegment.analysis_run_id, run.status),
            *_base_filters(user_id, start_date, end_date),
        )
        .order_by(score.desc(), Diary.diary_date.desc())
        .all()
    )
    events: dict = {}
    for row in rows:
        item = events.setdefault(row.event_id, {
            "diary_id": row.diary_id, "diary_date": row.diary_date, "keyword_score": float(row.score or 0),
            "keyword_matches": [], "semantic_matches": [],
        })
        item["keyword_score"] = max(item["keyword_score"], float(row.score or 0))
        item["keyword_matches"].append({
            "event_id": row.event_id, "analysis_run_id": row.analysis_run_id, "kind": row.kind,
            "semantic_layer": None, "snippet": _snippet(row.content, q), "keyword_matched": True,
            "_score": float(row.score or 0),
        })
    return events


def _semantic_events(db: Session, user_id: Any, q: str, start_date: Optional[date], end_date: Optional[date]) -> dict:
    vector = _embed_query(q)
    if vector is None:
        return {}
    current_run = aliased(AnalysisRun)
    distance = EventEmbeddingChunk.embedding.cosine_distance(vector)
    state_match = or_(
        and_(EventEmbeddingChunk.analysis_run_id.is_(None), SearchSemanticIndexState.analysis_run_id.is_(None)),
        EventEmbeddingChunk.analysis_run_id == SearchSemanticIndexState.analysis_run_id,
    )
    valid_analysis = or_(
        and_(EventEmbeddingChunk.chunk_type == "event_content", EventEmbeddingChunk.analysis_run_id.is_(None)),
        and_(EventEmbeddingChunk.chunk_type != "event_content", current_run.status == "CURRENT"),
    )
    rows = (
        db.query(
            EventEmbeddingChunk.event_id, EventEmbeddingChunk.analysis_run_id,
            EventEmbeddingChunk.chunk_type, EventEmbeddingChunk.content,
            Diary.id.label("diary_id"), Diary.diary_date, distance.label("distance"),
        )
        .join(SearchSemanticIndexState, and_(
            SearchSemanticIndexState.event_id == EventEmbeddingChunk.event_id,
            SearchSemanticIndexState.chunk_type == EventEmbeddingChunk.chunk_type,
            state_match,
            SearchSemanticIndexState.status == "READY",
        ))
        .join(DiaryEvent, DiaryEvent.id == EventEmbeddingChunk.event_id)
        .join(DiaryOrganized, DiaryOrganized.id == DiaryEvent.diary_organized_id)
        .join(Diary, Diary.id == DiaryOrganized.diary_id)
        .outerjoin(current_run, current_run.id == EventEmbeddingChunk.analysis_run_id)
        .filter(valid_analysis, *_base_filters(user_id, start_date, end_date))
        .order_by(distance.asc())
        .limit(SEMANTIC_CHUNK_FETCH_LIMIT)
        .all()
    )
    events: dict = {}
    for row in rows:
        similarity = 1.0 - float(row.distance)
        if similarity < SEMANTIC_MIN_SIMILARITY:
            continue
        # 语义块中若也包含原查询词，则该内容同时具备关键词命中条件。
        # 传入查询词以生成同口径摘要，并让前端按混合命中高亮。
        literal_keyword_match = q.casefold() in (row.content or "").casefold()
        existing = events.get(row.event_id)
        if existing is None:
            if len(events) >= SEMANTIC_CANDIDATE_CAP:
                continue
            existing = events[row.event_id] = {
                "diary_id": row.diary_id, "diary_date": row.diary_date, "semantic_score": similarity,
                "keyword_matches": [], "semantic_matches": [],
            }
        existing["semantic_score"] = max(existing["semantic_score"], similarity)
        existing["semantic_matches"].append({
            "event_id": row.event_id, "analysis_run_id": row.analysis_run_id, "kind": "semantic",
            "semantic_layer": row.chunk_type,
            "snippet": _snippet(row.content, q if literal_keyword_match else None),
            "keyword_matched": literal_keyword_match,
            "_score": similarity,
        })
    return events


def _semantic_status(db: Session, user_id: Any, start_date: Optional[date], end_date: Optional[date]) -> str:
    current_run = aliased(AnalysisRun)
    pending = (
        db.query(SearchSemanticIndexState.id)
        .join(DiaryEvent, DiaryEvent.id == SearchSemanticIndexState.event_id)
        .join(DiaryOrganized, DiaryOrganized.id == DiaryEvent.diary_organized_id)
        .join(Diary, Diary.id == DiaryOrganized.diary_id)
        .outerjoin(current_run, current_run.id == SearchSemanticIndexState.analysis_run_id)
        .filter(
            SearchSemanticIndexState.status == "PENDING",
            or_(SearchSemanticIndexState.analysis_run_id.is_(None), current_run.status == "CURRENT"),
            *_base_filters(user_id, start_date, end_date),
        ).first()
    )
    return "PARTIAL" if pending else "READY"


def _rank_diaries(keyword_events: dict, semantic_events: dict) -> list[dict]:
    """先算事件级 RRF，再选择每篇日记的最佳事件。

    不把同一日记内不同事件的关键词分和语义分拼接：那会制造一个现实中不存在的
    “最佳事件”，违反“日记取最佳事件 RRF”的排序语义。
    """
    events: dict = {}
    for source, score_key in ((keyword_events, "keyword_score"), (semantic_events, "semantic_score")):
        for event_id, value in source.items():
            event = events.setdefault(event_id, {
                "event_id": event_id, "diary_id": value["diary_id"], "diary_date": value["diary_date"],
                "keyword_score": None, "semantic_score": None, "keyword_matches": [], "semantic_matches": [],
            })
            event[score_key] = value[score_key]
            event["keyword_matches"].extend(value.get("keyword_matches", []))
            event["semantic_matches"].extend(value.get("semantic_matches", []))
    for score_key, rank_key in (("keyword_score", "keyword_rank"), ("semantic_score", "semantic_rank")):
        ordered = sorted((item for item in events.values() if item[score_key] is not None), key=lambda item: item[score_key], reverse=True)
        for rank, item in enumerate(ordered, 1):
            item[rank_key] = rank
    for event in events.values():
        event["rrf_score"] = sum(1.0 / (RRF_K + event[key]) for key in ("keyword_rank", "semantic_rank") if event.get(key))
    diaries: dict = {}
    for event in events.values():
        current = diaries.get(event["diary_id"])
        if current is None:
            current = diaries[event["diary_id"]] = {
                "diary_id": event["diary_id"], "diary_date": event["diary_date"],
                "best_event": event, "events": [],
            }
        current["events"].append(event)
        if event["rrf_score"] > current["best_event"]["rrf_score"]:
            current["best_event"] = event
    ordered = sorted(diaries.values(), key=lambda item: (item["best_event"]["rrf_score"], item["diary_date"]), reverse=True)
    for rank, diary in enumerate(ordered, 1):
        diary["rrf_rank"] = rank
    return ordered


def _serialize_results(db: Session, diaries: list[dict]) -> list[dict]:
    ids = [item["diary_id"] for item in diaries]
    titles = dict(db.query(DiaryOrganized.diary_id, DiaryOrganized.title).filter(DiaryOrganized.diary_id.in_(ids)).all()) if ids else {}
    result = []
    for diary in diaries:
        matches = []
        seen = set()
        # 摘要按各自命中分倒序，默认显示的前三条就是最相关内容。
        all_events = diary["events"]
        for event in all_events:
            for match in event["keyword_matches"]:
                key = (match["event_id"], match["kind"], match["snippet"])
                if key in seen:
                    continue
                seen.add(key)
                matches.append(match)
            for match in event["semantic_matches"]:
                key = (match["event_id"], match["semantic_layer"], match["snippet"])
                if key not in seen:
                    seen.add(key)
                    matches.append(match)
        matches.sort(key=lambda match: match.get("_score", 0), reverse=True)
        result.append({
            "diary_id": diary["diary_id"], "title": titles.get(diary["diary_id"]), "diary_date": diary["diary_date"],
            "ranking": {key: diary["best_event"].get(key) if key != "rrf_rank" else diary["rrf_rank"] for key in ("keyword_score", "keyword_rank", "semantic_score", "semantic_rank", "rrf_score", "rrf_rank")},
            "matches": [{key: value for key, value in match.items() if key != "_score"} for match in matches],
        })
    return result


def search_diaries(db: Session, user_id: Any, q: str, start_date: Optional[date] = None,
                   end_date: Optional[date] = None, limit: int = 20, offset: int = 0) -> tuple[list[dict], int, str]:
    query = (q or "").strip()
    if not query:
        return [], 0, "READY"
    keyword = _keyword_events(db, user_id, query, start_date, end_date)
    try:
        semantic = _semantic_events(db, user_id, query, start_date, end_date)
        semantic_status = _semantic_status(db, user_id, start_date, end_date)
    except Exception as exc:  # embedding 服务或 pgvector 不可用，不阻断关键词检索
        logger.warning("语义搜索不可用，回退关键词：%s", exc)
        semantic, semantic_status = {}, "UNAVAILABLE"
    ranked = _rank_diaries(keyword, semantic)
    total = len(ranked)
    return _serialize_results(db, ranked[offset: offset + limit]), total, semantic_status


def _rrf_fuse(keyword_list: list, semantic_list: list, k: int = RRF_K) -> tuple[list, dict]:
    """保留为纯函数，供 RRF 单元测试复用；正式搜索使用日记级 _rank_diaries。"""
    scores, meta = {}, {}
    for rows in (keyword_list, semantic_list):
        for rank, row in enumerate(rows, 1):
            event_id = row[0]
            scores[event_id] = scores.get(event_id, 0.0) + 1.0 / (k + rank)
            meta[event_id] = (row[1], row[2])
    return sorted(scores, key=lambda event_id: scores[event_id], reverse=True), meta


def search_events(db: Session, user_id: Any, q: str, start_date: Optional[date] = None,
                  end_date: Optional[date] = None, limit: int = 20, offset: int = 0,
                  mode: str = "hybrid") -> tuple[list[dict], int]:
    """已废弃的内部别名；返回新的日记级结果，mode 不再参与行为。"""
    items, total, _ = search_diaries(db, user_id, q, start_date, end_date, limit, offset)
    return items, total
