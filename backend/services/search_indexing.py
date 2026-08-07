"""日记级搜索索引写入。

关键词索引在事件/分析提交后立即重建；语义索引状态先置为 PENDING，再由后台
embedding 任务置 READY。所有分析来源都带 analysis_run_id，查询时再以 CURRENT
状态过滤，因此轮次切换不会泄漏旧分析内容。
"""

import json
import hashlib
from typing import Iterable

from sqlalchemy.orm import Session

from models.diary import (
    AnalysisItem,
    DiaryEvent,
    SearchKeywordSegment,
    SearchSemanticIndexState,
)
from services.analysis_history import get_current_analysis_run
from services.event_chunk_builder import build_event_chunk_contents


def _paragraphs(value: object) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except (TypeError, json.JSONDecodeError):
            return [value] if value.strip() else []
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    return [str(value).strip()] if str(value).strip() else []


def rebuild_event_keyword_segments(db: Session, event_id: object) -> int:
    """以当前事件和 CURRENT 分析重建可展示关键词片段。"""
    event = db.get(DiaryEvent, event_id)
    if event is None or event.organized is None:
        return 0
    diary_id = event.organized.diary_id
    db.query(SearchKeywordSegment).filter(SearchKeywordSegment.event_id == event.id).delete(
        synchronize_session=False
    )
    rows: list[SearchKeywordSegment] = []
    values: Iterable[tuple[str, object]] = (
        ("event_title", event.event_title),
        ("body", event.body),
        ("feeling", event.feeling),
        ("reflection", event.reflection),
    )
    for kind, value in values:
        for content in _paragraphs(value):
            rows.append(SearchKeywordSegment(diary_id=diary_id, event_id=event.id, kind=kind, content=content))

    run = get_current_analysis_run(db, diary_id)
    if run is not None:
        items = (
            db.query(AnalysisItem)
            .filter(AnalysisItem.analysis_run_id == run.id, AnalysisItem.scope == "EVENT", AnalysisItem.event_id == event.id)
            .order_by(AnalysisItem.sort_order)
            .all()
        )
        for item in items:
            if item.question and item.question.strip():
                rows.append(SearchKeywordSegment(
                    diary_id=diary_id, event_id=event.id, analysis_run_id=run.id,
                    kind=f"analysis_{item.analysis_type.lower()}_question", content=item.question.strip(),
                ))
            if item.content and item.content.strip():
                rows.append(SearchKeywordSegment(
                    diary_id=diary_id, event_id=event.id, analysis_run_id=run.id,
                    kind=f"analysis_{item.analysis_type.lower()}", content=item.content.strip(),
                ))
    db.add_all(rows)
    db.flush()
    return len(rows)


def mark_event_semantic_pending(db: Session, event_id: object) -> set[str]:
    """标记当前应有语义层为 PENDING；旧 READY 块立即失去查询资格。"""
    event = db.get(DiaryEvent, event_id)
    if event is None or event.organized is None:
        return set()
    run = get_current_analysis_run(db, event.organized.diary_id)
    contents = build_event_chunk_contents(db, event.id, run.id if run else None)
    expected = set(contents)
    db.query(SearchSemanticIndexState).filter(SearchSemanticIndexState.event_id == event.id).delete(
        synchronize_session=False
    )
    for chunk_type in expected:
        db.add(SearchSemanticIndexState(
            event_id=event.id,
            analysis_run_id=None if chunk_type == "event_content" else (run.id if run else None),
            chunk_type=chunk_type,
            content_hash=hashlib.sha256(contents[chunk_type].encode("utf-8")).hexdigest(),
            status="PENDING",
        ))
    db.flush()
    return expected


def refresh_event_search_indexes(db: Session, event_id: object) -> set[str]:
    """业务提交后的同步部分：关键词立即可用，语义层进入异步队列。"""
    rebuild_event_keyword_segments(db, event_id)
    return mark_event_semantic_pending(db, event_id)
