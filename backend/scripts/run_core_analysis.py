"""Run only core analysis (step 8) for one diary.

Usage:
    cd backend
    venv/bin/python scripts/run_core_analysis.py DIARY_ID
    venv/bin/python scripts/run_core_analysis.py DIARY_ID --persist
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))
os.chdir(BACKEND_DIR)

from database import SessionLocal
from models.diary import Diary, DiaryAnalysis, DiaryEvent
from services.analysis_pipeline import core_analysis

CORE_EVENT_FIELDS = {
    "emotion_analyses": ("event_emotion_analyses", "emotion_analyses"),
    "behavior_decision_analyses": (
        "event_behavior_decision_analyses",
        "behavior_decision_analyses",
    ),
    "self_understanding_analyses": (
        "event_self_understanding_analyses",
        "self_understanding_analyses",
    ),
    "action_suggestions": ("event_action_suggestions", "action_suggestions"),
}


def json_dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False)


def json_loads_or_empty(value: str | None) -> dict[str, Any]:
    if not value:
        return {}
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def get_event_items(event_array: list[Any], event_index: int, inner_key: str) -> list[Any]:
    for item in event_array:
        if isinstance(item, dict) and item.get("event_index") == event_index:
            value = item.get(inner_key, [])
            return value if isinstance(value, list) else []
    return []


def load_events(diary_id: str) -> tuple[dict[str, Any], list[dict[str, str]]]:
    db = SessionLocal()
    try:
        diary_uuid = uuid.UUID(diary_id)
        diary = db.query(Diary).filter(Diary.id == diary_uuid).first()
        if diary is None:
            raise RuntimeError(f"日记不存在: {diary_id}")
        if diary.organized is None:
            raise RuntimeError(f"日记尚无整理结果: {diary_id}")

        event_rows = (
            db.query(DiaryEvent)
            .filter(DiaryEvent.diary_organized_id == diary.organized.id)
            .order_by(DiaryEvent.sort_order)
            .all()
        )
        events = [
            {
                "title": row.event_title or "",
                "body": row.body or "",
                "feeling": row.feeling or "",
                "reflection": row.reflection or "",
            }
            for row in event_rows
        ]
        diary_info = {
            "diary_id": str(diary.id),
            "diary_organized_id": str(diary.organized.id),
            "organized_task_id": str(diary.organized.task_id),
            "mood": diary.organized.mood or "",
        }
        return diary_info, events
    finally:
        db.close()


def persist_core_analysis(diary_info: dict[str, Any], result: dict[str, Any]) -> None:
    db = SessionLocal()
    try:
        organized_id = uuid.UUID(diary_info["diary_organized_id"])
        task_id = uuid.UUID(diary_info["organized_task_id"])

        analysis = (
            db.query(DiaryAnalysis)
            .filter(DiaryAnalysis.diary_organized_id == organized_id)
            .first()
        )
        if analysis is None:
            analysis = DiaryAnalysis(
                task_id=task_id,
                diary_organized_id=organized_id,
                mood=diary_info.get("mood", ""),
            )
            db.add(analysis)

        analysis.emotion_analyses = json_dumps(result.get("diary_emotion_analyses", []))
        analysis.behavior_decision_analyses = json_dumps(
            result.get("diary_behavior_decision_analyses", [])
        )
        analysis.self_understanding_analyses = json_dumps(
            result.get("diary_self_understanding_analyses", [])
        )
        analysis.action_suggestions = json_dumps(
            result.get("diary_action_suggestions", [])
        )
        analysis.updated_at = datetime.utcnow()

        event_rows = (
            db.query(DiaryEvent)
            .filter(DiaryEvent.diary_organized_id == organized_id)
            .order_by(DiaryEvent.sort_order)
            .all()
        )
        for event_index, event_row in enumerate(event_rows):
            event_analysis = json_loads_or_empty(event_row.analysis)
            for target_key, (event_array_key, inner_key) in CORE_EVENT_FIELDS.items():
                event_analysis[target_key] = get_event_items(
                    result.get(event_array_key, []),
                    event_index,
                    inner_key,
                )
            event_row.analysis = json_dumps(event_analysis)

        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


async def run(diary_id: str, persist: bool) -> dict[str, Any]:
    diary_info, events = load_events(diary_id)
    result = await core_analysis(
        {
            "task_id": str(uuid.uuid4()),
            "diary_id": diary_id,
            "diary_organized_id": diary_info["diary_organized_id"],
            "structured_diary": {"events": events},
        }
    )
    if persist:
        persist_core_analysis(diary_info, result)
    return result

def main() -> None:
    result = asyncio.run(run("7fe4c154-1190-401c-a6fc-1697146f93e7", False))
    print(json_dumps(result))


if __name__ == "__main__":
    main()
