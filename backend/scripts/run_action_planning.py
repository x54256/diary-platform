"""独立真实调用「行动规划」分析环节。

使用方式：
    cd backend
    venv/bin/python scripts/run_action_planning.py

只需要修改本文件顶部的 DIARY_ID。脚本会读取该日记已有的整理结果和当前分析轮次，
只调用 action_planning，不会重新执行其它分析环节。
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

# 手动修改这里，再运行脚本。
DIARY_ID = "00000000-0000-0000-0000-000000000000"
# True 会把本次行动规划结果写入 diary_action_items；False 只调用模型并打印结果。
PERSIST_ACTION_ITEMS = False

from database import SessionLocal
from models.diary import Diary, DiaryEvent
from services.action_items import apply_action_planning_result
from services.analysis_history import get_current_analysis_run, run_to_state
from services.analysis_pipeline import _action_planning_input, action_planning


def parse_json_list(value: Any) -> list:
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError:
            return []
    return value if isinstance(value, list) else []


def load_input(diary_id: uuid.UUID) -> tuple[dict[str, Any], Any, uuid.UUID]:
    db = SessionLocal()
    try:
        diary = db.query(Diary).filter(Diary.id == diary_id).first()
        if diary is None:
            raise RuntimeError(f"日记不存在: {diary_id}")
        if diary.organized is None:
            raise RuntimeError(f"日记尚未完成整理: {diary_id}")

        run = get_current_analysis_run(db, diary_id)
        if run is None:
            raise RuntimeError(f"日记尚未完成分析，没有可供行动规划使用的当前分析轮次: {diary_id}")

        events = (
            db.query(DiaryEvent)
            .filter(DiaryEvent.diary_organized_id == diary.organized.id)
            .order_by(DiaryEvent.sort_order)
            .all()
        )
        structured_diary = {
            "diary_date": diary.diary_date.isoformat(),
            "plans": parse_json_list(diary.organized.plans),
            "events": [
                {
                    "title": event.event_title or "",
                    "body": parse_json_list(event.body),
                    "feeling": parse_json_list(event.feeling),
                    "reflection": parse_json_list(event.reflection),
                }
                for event in events
            ],
        }
        state = run_to_state(run, events)
        state.update({
            "task_id": str(uuid.uuid4()),
            "diary_id": str(diary.id),
            "user_id": str(diary.user_id),
            "diary_organized_id": str(diary.organized.id),
            "structured_diary": structured_diary,
        })
        return state, run, diary.user_id
    finally:
        db.close()


async def run() -> dict[str, Any]:
    diary_id = uuid.UUID(DIARY_ID)
    state, current_run, user_id = load_input(diary_id)
    planning_input = _action_planning_input(state)
    if not planning_input["plans"] and not planning_input["action_suggestions"]:
        raise RuntimeError("该日记没有后续计划或可行动建议，行动规划节点会跳过大模型调用")
    result = await action_planning(state)

    if PERSIST_ACTION_ITEMS:
        db = SessionLocal()
        try:
            apply_action_planning_result(
                db,
                diary_id=diary_id,
                user_id=user_id,
                generation_run_id=current_run.id,
                action_items=result.get("action_items", []),
            )
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    return result


if __name__ == "__main__":
    print(json.dumps(asyncio.run(run()), ensure_ascii=False, indent=2, default=str))
