"""Run analysis step 8 or 9 for one diary.

Usage:
    cd backend
    venv/bin/python scripts/run_core_analysis.py
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import uuid
from pathlib import Path
from typing import Any

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))
os.chdir(BACKEND_DIR)

from database import SessionLocal
from models.diary import Diary, DiaryEvent
from services.analysis_history import create_analysis_run_from_state
from services.analysis_pipeline import cognition_analysis, core_analysis


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


def get_event_items(event_analyses: list[Any], event_index: int, inner_key: str) -> list[Any]:
    if event_index >= len(event_analyses):
        return []
    item = event_analyses[event_index]
    if not isinstance(item, dict):
        return []
    value = item.get(inner_key, [])
    return value if isinstance(value, list) else []


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


def persist_analysis(diary_info: dict[str, Any], result: dict[str, Any]) -> None:
    db = SessionLocal()
    try:
        state = {
            "task_id": str(uuid.uuid4()),
            "diary_id": diary_info["diary_id"],
            "diary_organized_id": diary_info["diary_organized_id"],
            "mood": diary_info.get("mood", ""),
            **result,
        }
        create_analysis_run_from_state(db, state, diary_info["diary_organized_id"])
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


async def run(diary_id: str, phase: str, persist: bool) -> dict[str, Any]:
    diary_info, events = load_events(diary_id)
    state = {
        "task_id": str(uuid.uuid4()),
        "diary_id": diary_id,
        "diary_organized_id": diary_info["diary_organized_id"],
        "structured_diary": {"events": events},
    }
    result = await core_analysis(state) if phase == "8" else await cognition_analysis(state)
    if persist:
        persist_analysis(diary_info, result)
    return result


def main() -> None:
    DIARY_ID = "7fe4c154-1190-401c-a6fc-1697146f93e7"
    PHASE = "9"  # "8" or "9"
    PERSIST = True
    if PHASE not in {"8", "9"}:
        raise RuntimeError(f"PHASE must be '8' or '9', got: {PHASE}")

    result = asyncio.run(run(DIARY_ID, PHASE, PERSIST))
    print(json_dumps(result))


if __name__ == "__main__":
    main()
