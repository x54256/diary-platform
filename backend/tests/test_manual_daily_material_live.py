"""手工验证每日提炼的真实模型调用。

使用方式：
1. 将 ``DIARY_ID`` 改为待验证的日记 ID。
2. 执行：
   ``PYTHONPATH=backend uv run --with-requirements backend/requirements.txt pytest -s backend/tests/test_manual_daily_material_live.py``

该测试默认跳过，且全程只读数据库：它不会创建回顾任务、冻结来源或写入每日提炼表。
"""

from __future__ import annotations

import json
import unittest
import uuid
from typing import Any

from sqlalchemy.orm import joinedload

from database import SessionLocal
from models.diary import Diary, DiaryAnnotation, DiaryOrganized
from services.review_ai import review_daily_material


# 手工填写后才会执行真实模型调用。
DIARY_ID = ""


def _text_list(value: Any) -> list[str]:
    """保留结构化日记字段中的完整原句。"""
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return [value.strip()] if value.strip() else []
        if isinstance(parsed, list):
            return [str(item).strip() for item in parsed if str(item).strip()]
        return [str(parsed).strip()] if str(parsed).strip() else []
    return [str(value).strip()] if str(value).strip() else []


def _load_payload(diary_id: str) -> dict[str, Any]:
    db = SessionLocal()
    try:
        try:
            diary_uuid = uuid.UUID(diary_id)
        except ValueError as exc:
            raise AssertionError(f"DIARY_ID 不是合法 UUID：{diary_id}") from exc
        diary = (
            db.query(Diary)
            .options(joinedload(Diary.organized).joinedload(DiaryOrganized.events))
            .filter(Diary.id == diary_uuid)
            .first()
        )
        if diary is None:
            raise AssertionError(f"日记不存在：{diary_id}")
        if diary.organized is None:
            raise AssertionError(f"日记尚未完成整理：{diary_id}")

        annotations = (
            db.query(DiaryAnnotation)
            .options(joinedload(DiaryAnnotation.comments))
            .filter(
                DiaryAnnotation.diary_id == diary.id,
                DiaryAnnotation.event_id.isnot(None),
                DiaryAnnotation.deleted_at.is_(None),
            )
            .all()
        )
        notes_by_event: dict[str, list[str]] = {}
        for annotation in annotations:
            notes = [f"用户划线：{annotation.selected_text}"]
            comments = [
                comment.content.strip()
                for comment in annotation.comments
                if comment.deleted_at is None and comment.content.strip()
            ]
            if comments:
                notes.append("用户评论：" + "；".join(comments))
            notes_by_event.setdefault(str(annotation.event_id), []).append("\n".join(notes))

        events = []
        for event in sorted(diary.organized.events, key=lambda item: (item.sort_order, str(item.id))):
            importance = event.user_importance or event.ai_importance
            if importance not in {"HIGH", "MEDIUM"}:
                continue
            events.append({
                "event_no": len(events) + 1,
                "title": event.event_title or "未命名事件",
                "body": _text_list(event.body),
                "feeling": _text_list(event.feeling),
                "reflection": _text_list(event.reflection),
                "related_user_notes": notes_by_event.get(str(event.id), []),
            })
        if not events:
            raise AssertionError("该日记没有重要程度为 HIGH 或 MEDIUM 的事件，无法生成每日提炼")
        return {"date": diary.diary_date.isoformat(), "events": events}
    finally:
        db.close()


@unittest.skipIf(not DIARY_ID, "请先在本文件填写 DIARY_ID 后再执行")
class TestManualDailyMaterialLive(unittest.IsolatedAsyncioTestCase):
    async def test_generate_daily_material_with_real_model(self) -> None:
        payload = _load_payload(DIARY_ID)
        print("每日提炼请求：")
        print(json.dumps(payload, ensure_ascii=False, indent=2))

        result = await review_daily_material(payload)

        print("每日提炼结果：")
        print(json.dumps(result, ensure_ascii=False, indent=2))
        self.assertIn("day_overview", result)
        self.assertIn("matters", result)
