"""分析历史与反馈服务"""

import json
import uuid
from datetime import datetime
from typing import Any, Dict, Iterable, Optional

from sqlalchemy.orm import Session

from models.diary import AnalysisFeedback, AnalysisItem, AnalysisRun, DiaryAnnotation, DiaryEvent


ANALYSIS_TYPE_TITLES = {
    "EMOTION": "情绪分析",
    "BEHAVIOR_DECISION": "行为与决策分析",
    "SELF_UNDERSTANDING": "关注点与需求",
    "ACTION_SUGGESTION": "可行动建议",
    "COGNITIVE_CALIBRATION": "认知校准",
    "COGNITIVE_ENHANCEMENT": "认知完善",
    "QUESTION_ANSWER": "问题解答",
}

ANALYSIS_TYPE_FIELDS = {
    "EMOTION": "emotion_analyses",
    "BEHAVIOR_DECISION": "behavior_decision_analyses",
    "SELF_UNDERSTANDING": "self_understanding_analyses",
    "ACTION_SUGGESTION": "action_suggestions",
    "COGNITIVE_CALIBRATION": "cognitive_calibration_analyses",
    "COGNITIVE_ENHANCEMENT": "cognitive_enhancements",
}

UNDERSTANDING_TYPES = ["EMOTION", "BEHAVIOR_DECISION", "SELF_UNDERSTANDING", "ACTION_SUGGESTION"]
COGNITION_TYPES = ["COGNITIVE_CALIBRATION", "QUESTION_ANSWER", "COGNITIVE_ENHANCEMENT"]
ALL_ANALYSIS_TYPES = UNDERSTANDING_TYPES + COGNITION_TYPES
CORE_ANALYSIS_TYPES = set(UNDERSTANDING_TYPES)
COGNITION_ANALYSIS_TYPES = set(COGNITION_TYPES)


def normalize_uuid(value: Any) -> Any:
    if isinstance(value, str):
        return uuid.UUID(value)
    return value


def safe_list(value: Any) -> list:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, list) else []
        except (TypeError, json.JSONDecodeError):
            return []
    return []


def section_key(scope: str, event_id: Any, analysis_type: str) -> tuple:
    return (scope, str(event_id) if event_id else None, analysis_type)


def get_current_analysis_run(db: Session, diary_id: Any) -> Optional[AnalysisRun]:
    return (
        db.query(AnalysisRun)
        .filter(
            AnalysisRun.diary_id == normalize_uuid(diary_id),
            AnalysisRun.status == "CURRENT",
        )
        .order_by(AnalysisRun.created_at.desc())
        .first()
    )


def archive_current_runs(db: Session, diary_id: Any) -> None:
    (
        db.query(AnalysisRun)
        .filter(
            AnalysisRun.diary_id == normalize_uuid(diary_id),
            AnalysisRun.status == "CURRENT",
        )
        .update({"status": "ARCHIVED", "updated_at": datetime.utcnow()}, synchronize_session=False)
    )


def add_text_items(
    db: Session,
    run_id: uuid.UUID,
    scope: str,
    event_id: Optional[uuid.UUID],
    analysis_type: str,
    values: Iterable[Any],
) -> None:
    for idx, value in enumerate(values or []):
        if not isinstance(value, str) or not value.strip():
            continue
        db.add(
            AnalysisItem(
                analysis_run_id=run_id,
                scope=scope,
                event_id=event_id,
                analysis_type=analysis_type,
                content=value,
                sort_order=idx,
            )
        )


def add_question_answer_items(
    db: Session,
    run_id: uuid.UUID,
    scope: str,
    event_id: Optional[uuid.UUID],
    values: Iterable[Any],
) -> None:
    for idx, value in enumerate(values or []):
        if not isinstance(value, dict):
            continue
        answer = value.get("answer")
        if not isinstance(answer, str) or not answer.strip():
            continue
        db.add(
            AnalysisItem(
                analysis_run_id=run_id,
                scope=scope,
                event_id=event_id,
                analysis_type="QUESTION_ANSWER",
                question=value.get("question"),
                content=answer,
                sort_order=idx,
            )
        )


def reconcile_analysis_annotations(
    db: Session,
    previous_items: list[AnalysisItem],
    current_items: list[AnalysisItem],
) -> None:
    """分析重跑后保留未变化区块的批注，失效区块执行逻辑删除。"""
    current_by_key = {
        (
            item.scope,
            str(item.event_id) if item.event_id else None,
            item.analysis_type,
            item.sort_order,
        ): item
        for item in current_items
    }
    now = datetime.utcnow()
    for previous_item in previous_items:
        annotations = (
            db.query(DiaryAnnotation)
            .filter(
                DiaryAnnotation.analysis_item_id == previous_item.id,
                DiaryAnnotation.deleted_at.is_(None),
            )
            .all()
        )
        if not annotations:
            continue
        key = (
            previous_item.scope,
            str(previous_item.event_id) if previous_item.event_id else None,
            previous_item.analysis_type,
            previous_item.sort_order,
        )
        current_item = current_by_key.get(key)
        unchanged = bool(
            current_item
            and current_item.content == previous_item.content
            and current_item.question == previous_item.question
        )
        for annotation in annotations:
            if unchanged:
                annotation.analysis_item_id = current_item.id
                annotation.updated_at = now
            else:
                annotation.deleted_at = now
                annotation.deleted_reason = "analysis_changed"
                annotation.updated_at = now


def extract_event_items(event_items: Any, event_idx: int, inner_key: str) -> list:
    if not isinstance(event_items, list) or event_idx >= len(event_items):
        return []
    item = event_items[event_idx]
    if not isinstance(item, dict):
        return []
    value = item.get(inner_key, [])
    return value if isinstance(value, list) else []


def create_analysis_run_from_state(
    db: Session,
    state: Dict[str, Any],
    diary_organized_id: Any,
    feedback_source_run_id: Any = None,
    inherited_feedback_keys: set[tuple] | None = None,
) -> AnalysisRun:
    """把流水线 state 保存为新的完整分析轮次。"""
    diary_id = normalize_uuid(state["diary_id"])
    task_id = normalize_uuid(state["task_id"])
    org_id = normalize_uuid(diary_organized_id)

    previous_run = get_current_analysis_run(db, diary_id)
    previous_items = list(previous_run.items) if previous_run else []
    archive_current_runs(db, diary_id)

    run = AnalysisRun(
        diary_id=diary_id,
        diary_organized_id=org_id,
        task_id=task_id,
        mood=state.get("mood", ""),
        status="CURRENT",
    )
    db.add(run)
    db.flush()

    diary_analysis = state.get("diary_analysis", {})
    if not isinstance(diary_analysis, dict):
        diary_analysis = {}

    for analysis_type, field_name in ANALYSIS_TYPE_FIELDS.items():
        if analysis_type == "COGNITIVE_CALIBRATION":
            values = state.get("diary_cognitive_calibration_analyses", [])
        elif analysis_type == "COGNITIVE_ENHANCEMENT":
            values = state.get("diary_cognitive_enhancements", [])
        else:
            values = diary_analysis.get(field_name, [])
        add_text_items(db, run.id, "DIARY", None, analysis_type, values)

    event_records = (
        db.query(DiaryEvent)
        .filter(DiaryEvent.diary_organized_id == org_id)
        .order_by(DiaryEvent.sort_order)
        .all()
    )
    for idx, event_record in enumerate(event_records):
        for analysis_type, field_name in ANALYSIS_TYPE_FIELDS.items():
            if analysis_type in {"EMOTION", "BEHAVIOR_DECISION", "SELF_UNDERSTANDING", "ACTION_SUGGESTION"}:
                values = extract_event_items(state.get("event_analyses", []), idx, field_name)
            elif analysis_type == "COGNITIVE_CALIBRATION":
                values = extract_event_items(
                    state.get("event_cognitive_calibration_analyses", []),
                    idx,
                    field_name,
                )
            else:
                values = extract_event_items(state.get("event_cognitive_enhancements", []), idx, field_name)
            add_text_items(db, run.id, "EVENT", event_record.id, analysis_type, values)
        add_question_answer_items(
            db,
            run.id,
            "EVENT",
            event_record.id,
            extract_event_items(state.get("event_question_answers", []), idx, "question_answers"),
        )

    if feedback_source_run_id:
        copy_feedback_to_run(
            db,
            feedback_source_run_id,
            run,
            inherited_feedback_keys or set(),
        )

    db.flush()
    current_items = (
        db.query(AnalysisItem)
        .filter(AnalysisItem.analysis_run_id == run.id)
        .all()
    )
    reconcile_analysis_annotations(db, previous_items, current_items)

    return run


def feedback_response(feedback: AnalysisFeedback) -> dict:
    return {
        "id": feedback.id,
        "rating": feedback.rating,
        "comment": feedback.comment,
        "is_inherited": feedback.is_inherited,
        "source_feedback_id": feedback.source_feedback_id,
        "updated_at": feedback.updated_at,
    }


def copy_feedback_to_run(
    db: Session,
    source_run_id: Any,
    target_run: AnalysisRun,
    inherited_keys: set[tuple],
) -> None:
    """复制上一轮反馈到新轮次，改写过的块标记为待确认。"""
    source_feedbacks = (
        db.query(AnalysisFeedback)
        .filter(AnalysisFeedback.analysis_run_id == normalize_uuid(source_run_id))
        .all()
    )
    for feedback in source_feedbacks:
        key = section_key(feedback.scope, feedback.event_id, feedback.analysis_type)
        db.add(
            AnalysisFeedback(
                analysis_run_id=target_run.id,
                user_id=feedback.user_id,
                scope=feedback.scope,
                event_id=feedback.event_id,
                analysis_type=feedback.analysis_type,
                rating=feedback.rating,
                comment=feedback.comment,
                is_inherited=key in inherited_keys,
                source_feedback_id=feedback.id,
            )
        )


def build_sections(
    run: Optional[AnalysisRun],
    user_id: Any,
    scope: str,
    event_id: Any = None,
) -> list[dict]:
    if not run:
        return []

    feedback_by_key = {
        section_key(item.scope, item.event_id, item.analysis_type): item
        for item in run.feedbacks
        if item.user_id == user_id
    }

    sections = []
    for analysis_type in ALL_ANALYSIS_TYPES:
        items = [
            item
            for item in run.items
            if item.scope == scope
            and (str(item.event_id) if item.event_id else None) == (str(event_id) if event_id else None)
            and item.analysis_type == analysis_type
        ]
        if not items:
            continue
        feedback = feedback_by_key.get(section_key(scope, event_id, analysis_type))
        sections.append(
            {
                "scope": scope,
                "event_id": event_id,
                "analysis_type": analysis_type,
                "title": ANALYSIS_TYPE_TITLES[analysis_type],
                "items": [
                    {
                        "id": item.id,
                        "content": item.content,
                        "question": item.question,
                        "sort_order": item.sort_order,
                    }
                    for item in sorted(items, key=lambda item: item.sort_order)
                ],
                "feedback": feedback_response(feedback) if feedback else None,
            }
        )
    return sections


def build_run_response(run: Optional[AnalysisRun], user_id: Any) -> Optional[dict]:
    if not run:
        return None
    return {
        "id": run.id,
        "mood": run.mood,
        "status": run.status,
        "sections": build_sections(run, user_id, "DIARY"),
        "created_at": run.created_at,
        "updated_at": run.updated_at,
    }


def effective_feedback(db: Session, run_id: Any) -> list[AnalysisFeedback]:
    return (
        db.query(AnalysisFeedback)
        .filter(
            AnalysisFeedback.analysis_run_id == normalize_uuid(run_id),
            AnalysisFeedback.rating <= 3,
            AnalysisFeedback.is_inherited.is_(False),
            AnalysisFeedback.comment.isnot(None),
            AnalysisFeedback.comment != "",
        )
        .all()
    )


def feedback_keys_for_run(db: Session, run_id: Any) -> set[tuple]:
    feedbacks = (
        db.query(AnalysisFeedback)
        .filter(AnalysisFeedback.analysis_run_id == normalize_uuid(run_id))
        .all()
    )
    return {
        section_key(feedback.scope, feedback.event_id, feedback.analysis_type)
        for feedback in feedbacks
    }


def run_to_state(run: AnalysisRun, event_records: list[DiaryEvent]) -> dict:
    """把历史分析轮次还原成流水线结果形态，用于反馈重写合并。"""
    event_index = {event.id: idx for idx, event in enumerate(event_records)}
    event_count = len(event_records)
    state = {
        "mood": run.mood or "",
        "event_tags": [],
        "diary_analysis": {
            "emotion_analyses": [],
            "behavior_decision_analyses": [],
            "self_understanding_analyses": [],
            "action_suggestions": [],
        },
        "event_analyses": [
            {
                "title": event.event_title,
                "emotion_analyses": [],
                "behavior_decision_analyses": [],
                "self_understanding_analyses": [],
                "action_suggestions": [],
            }
            for event in event_records
        ],
        "diary_cognitive_calibration_analyses": [],
        "diary_cognitive_enhancements": [],
        "event_cognitive_calibration_analyses": [
            {"title": event.event_title, "cognitive_calibration_analyses": []}
            for event in event_records
        ],
        "event_question_answers": [
            {"title": event.event_title, "question_answers": []}
            for event in event_records
        ],
        "event_cognitive_enhancements": [
            {"title": event.event_title, "cognitive_enhancements": []}
            for event in event_records
        ],
    }

    type_to_field = {
        "EMOTION": "emotion_analyses",
        "BEHAVIOR_DECISION": "behavior_decision_analyses",
        "SELF_UNDERSTANDING": "self_understanding_analyses",
        "ACTION_SUGGESTION": "action_suggestions",
        "COGNITIVE_CALIBRATION": "cognitive_calibration_analyses",
        "COGNITIVE_ENHANCEMENT": "cognitive_enhancements",
        "QUESTION_ANSWER": "question_answers",
    }

    for item in sorted(run.items, key=lambda row: (row.scope, str(row.event_id), row.analysis_type, row.sort_order)):
        field_name = type_to_field.get(item.analysis_type)
        if not field_name:
            continue
        value: Any
        if item.analysis_type == "QUESTION_ANSWER":
            value = {"question": item.question or "", "answer": item.content}
        else:
            value = item.content

        if item.scope == "DIARY":
            if item.analysis_type in {"EMOTION", "BEHAVIOR_DECISION", "SELF_UNDERSTANDING", "ACTION_SUGGESTION"}:
                state["diary_analysis"][field_name].append(value)
            elif item.analysis_type == "COGNITIVE_CALIBRATION":
                state["diary_cognitive_calibration_analyses"].append(value)
            elif item.analysis_type == "COGNITIVE_ENHANCEMENT":
                state["diary_cognitive_enhancements"].append(value)
            continue

        idx = event_index.get(item.event_id)
        if idx is None or idx >= event_count:
            continue
        if item.analysis_type in {"EMOTION", "BEHAVIOR_DECISION", "SELF_UNDERSTANDING", "ACTION_SUGGESTION"}:
            state["event_analyses"][idx][field_name].append(value)
        elif item.analysis_type == "COGNITIVE_CALIBRATION":
            state["event_cognitive_calibration_analyses"][idx][field_name].append(value)
        elif item.analysis_type == "QUESTION_ANSWER":
            state["event_question_answers"][idx][field_name].append(value)
        elif item.analysis_type == "COGNITIVE_ENHANCEMENT":
            state["event_cognitive_enhancements"][idx][field_name].append(value)

    return state


def feedback_to_context(feedbacks: list[AnalysisFeedback], event_records: list[DiaryEvent]) -> list[dict]:
    event_titles = {event.id: event.event_title for event in event_records}
    result = []
    for feedback in feedbacks:
        result.append(
            {
                "scope": feedback.scope,
                "event_id": str(feedback.event_id) if feedback.event_id else None,
                "event_title": event_titles.get(feedback.event_id),
                "analysis_type": feedback.analysis_type,
                "rating": feedback.rating,
                "comment": feedback.comment,
            }
        )
    return result
