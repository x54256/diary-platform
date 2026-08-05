"""手工执行日记整理流水线的第一个环节：文本清洗。

使用方式：
1. 修改本文件顶部的 ``DIARY_ID``。
2. 执行：
   ``PYTHONPATH=backend uv run --with-requirements backend/requirements.txt pytest -s backend/tests/test_manual_text_clean_live.py``

本测试只读取日记和人物关系，并调用真实模型；不会创建、更新或清理整理任务，
也不会修改日记及其整理结果。结果会打印到终端，并保存到
``backend/tests/output/text_clean_<diary_id>.json``。
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path

from models.diary import Diary
from database import SessionLocal
from services.ai import CLEAN_PROMPT
from services.person_relations import load_person_name_gender_context
from services.pipeline import _get_llm, _invoke_llm


# 手工填写待清洗的日记 ID。
DIARY_ID = "abbe7b04-098a-4256-8396-2884284de7fd"

OUTPUT_DIR = Path(__file__).parent / "output"


def _load_diary_payload(diary_id: str) -> tuple[str, str, list[dict]]:
    """读取日记原文和整理环节使用的人物关系上下文。"""
    try:
        diary_uuid = uuid.UUID(diary_id)
    except ValueError as exc:
        raise AssertionError(f"DIARY_ID 不是合法 UUID：{diary_id}") from exc

    db = SessionLocal()
    try:
        diary = (
            db.query(Diary)
            .filter(Diary.id == diary_uuid, Diary.deleted_at.is_(None))
            .first()
        )
        if diary is None:
            raise AssertionError(f"日记不存在或已删除：{diary_id}")
        person_relations = load_person_name_gender_context(db, diary.user_id)
        return diary.original_text, diary.diary_date.isoformat(), person_relations
    finally:
        db.close()


def _save_result(diary_id: str, original_text: str, cleaned_text: str) -> Path:
    """保存本次文本清洗结果，不覆盖数据库中的任何结果。"""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    output_path = OUTPUT_DIR / f"text_clean_{diary_id}.json"
    output_path.write_text(
        json.dumps(
            {
                "diary_id": diary_id,
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "original_length": len(original_text),
                "cleaned_length": len(cleaned_text),
                "cleaned_text": cleaned_text,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    return output_path

import asyncio

class TestManualTextCleanLive:
    def test_text_clean_only(self) -> None:
        original_text, diary_date, person_relations = _load_diary_payload(DIARY_ID)
        llm = _get_llm(0.3, step_name="text_clean")

        # 使用 asyncio.run 执行协程，拿到真实返回字典
        result = asyncio.run(_invoke_llm(
            llm,
            CLEAN_PROMPT,
            json.dumps(
                {
                    "original_text": original_text,
                    "diary_date": diary_date,
                    "person_relations": person_relations,
                },
                ensure_ascii=False,
            ),
            step_name="text_clean_manual",
        ))

        cleaned_text = result.get("cleaned_text")
        assert isinstance(cleaned_text, str), "模型未返回 cleaned_text 字符串"
        assert cleaned_text.strip(), "模型返回了空的 cleaned_text"

        output_path = _save_result(DIARY_ID, original_text, cleaned_text)
        print(f"原文长度：{len(original_text)}")
        print(f"清洗结果长度：{len(cleaned_text)}")
        print(f"结果文件：{output_path}")
        print("\n===== 清洗结果 =====\n")
        print(cleaned_text)
