"""事件语义分块构建器：fact / self_understanding / cognition 三层纯文本聚合。

分块口径（决策 2，对齐 build_sections 的 EVENT 作用域）：
- fact              = event_title + body
- self_understanding = feeling + reflection + EVENT 作用域「理解类」分析
                      （EMOTION / BEHAVIOR_DECISION / SELF_UNDERSTANDING / ACTION_SUGGESTION）
- cognition         = EVENT 作用域「认知类」分析
                      （COGNITIVE_CALIBRATION / COGNITION_ENHANCEMENT / QUESTION_ANSWER）

分析内容取 CURRENT 轮次（与 search_text 触发器口径一致）。每层输出一份纯文本，
供 embedding 向量化；结果单位=事件，命中层经 matched_chunk_types 回传前端做高亮。
"""

import json
from typing import Dict, List, Optional

from sqlalchemy.orm import Session

from models.diary import AnalysisItem, DiaryEvent
from services.analysis_history import (
    COGNITION_TYPES,
    UNDERSTANDING_TYPES,
    get_current_analysis_run,
)

# 三层语义分块类型（与迁移 038 CHECK 约束 / matched_chunk_types / 前端映射一致）。
CHUNK_TYPE_FACT = "fact"
CHUNK_TYPE_SELF_UNDERSTANDING = "self_understanding"
CHUNK_TYPE_COGNITION = "cognition"

CHUNK_TYPES: tuple[str, ...] = (
    CHUNK_TYPE_FACT,
    CHUNK_TYPE_SELF_UNDERSTANDING,
    CHUNK_TYPE_COGNITION,
)

# 预置集合，O(1) 判断分析类型归属（避免每次查询重建集合）。
_UNDERSTANDING_SET = set(UNDERSTANDING_TYPES)
_COGNITION_SET = set(COGNITION_TYPES)


def _join_text_field(value: object) -> str:
    """将 diary_events 的 body/feeling/reflection（JSON 数组字符串或列表）合并为纯文本。

    空值、空数组、解析失败均安全降级为空串。
    """
    if value is None:
        return ""
    if isinstance(value, str):
        try:
            items = json.loads(value)
        except (TypeError, json.JSONDecodeError):
            return value.strip() if value.strip() else ""
    else:
        items = value
    if not isinstance(items, list):
        return "" if items is None else str(items)
    return "\n".join(str(item).strip() for item in items if isinstance(item, str) and item.strip())


def _event_fact_text(event: DiaryEvent) -> str:
    """fact 层：事件标题 + 正文。"""
    parts: List[str] = []
    if event.event_title:
        title = event.event_title.strip()
        if title:
            parts.append(title)
    body = _join_text_field(event.body)
    if body:
        parts.append(body)
    return "\n".join(parts).strip()


def _event_self_understanding_text(event: DiaryEvent, run: Optional[object]) -> str:
    """self_understanding 层：感受 + 反思 + EVENT 作用域理解类分析。"""
    parts: List[str] = []
    feeling = _join_text_field(event.feeling)
    if feeling:
        parts.append(feeling)
    reflection = _join_text_field(event.reflection)
    if reflection:
        parts.append(reflection)
    if run is not None:
        items = [
            item
            for item in run.items
            if item.scope == "EVENT"
            and (str(item.event_id) if item.event_id else None) == str(event.id)
            and item.analysis_type in _UNDERSTANDING_SET
        ]
        for item in sorted(items, key=lambda it: it.sort_order):
            line = (item.content or "").strip()
            if line:
                parts.append(line)
    return "\n".join(parts).strip()


def _event_cognition_text(event: DiaryEvent, run: Optional[object]) -> str:
    """cognition 层：EVENT 作用域认知类分析。"""
    parts: List[str] = []
    if run is not None:
        items = [
            item
            for item in run.items
            if item.scope == "EVENT"
            and (str(item.event_id) if item.event_id else None) == str(event.id)
            and item.analysis_type in _COGNITION_SET
        ]
        for item in sorted(items, key=lambda it: it.sort_order):
            if item.analysis_type == "QUESTION_ANSWER":
                question = (item.question or "").strip()
                answer = (item.content or "").strip()
                if question and answer:
                    parts.append(f"问：{question}\n答：{answer}")
                elif answer:
                    parts.append(answer)
            else:
                line = (item.content or "").strip()
                if line:
                    parts.append(line)
    return "\n".join(parts).strip()


def build_event_chunk_contents(db: Session, event_id: object) -> Dict[str, str]:
    """为单个事件构建三层分块纯文本。

    Args:
        db: 数据库会话。
        event_id: 目标事件 ID。

    Returns:
        {chunk_type: text}；仅包含非空文本的分层（未分析事件也会有 fact 层）。
        事件不存在时返回空字典。
    """
    event = db.get(DiaryEvent, event_id)
    if event is None:
        return {}

    diary_id = event.organized.diary_id if event.organized else None
    run = get_current_analysis_run(db, diary_id) if diary_id is not None else None

    contents: Dict[str, str] = {}
    fact = _event_fact_text(event)
    if fact:
        contents[CHUNK_TYPE_FACT] = fact
    self_understanding = _event_self_understanding_text(event, run)
    if self_understanding:
        contents[CHUNK_TYPE_SELF_UNDERSTANDING] = self_understanding
    cognition = _event_cognition_text(event, run)
    if cognition:
        contents[CHUNK_TYPE_COGNITION] = cognition
    return contents
