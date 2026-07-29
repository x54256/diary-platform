"""AI 模型清单初始化。"""

import csv
import logging
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.orm import Session

from models.model_config import ModelCatalog

logger = logging.getLogger("app.model_seed")

SEED_FILE = Path(__file__).resolve().parent.parent / "data" / "model_seed.csv"


def repair_model_management_schema(db: Session) -> None:
    """修复模型管理表结构。"""
    db.execute(text("ALTER TABLE channel_models DROP COLUMN IF EXISTS api_model_name"))
    db.execute(text("ALTER TABLE channel_models DROP COLUMN IF EXISTS protocol"))
    db.execute(text("""
        UPDATE model_catalog
        SET ability_category = CASE
            WHEN model_name ILIKE '%realtime%' THEN '实时语音识别'
            ELSE '录音文件识别'
        END
        WHERE model_type = 'asr'
          AND ability_category = '语音识别'
    """))
    db.commit()


def seed_model_catalog(db: Session) -> int:
    """幂等初始化模型清单，返回新增数量。"""
    if not SEED_FILE.exists():
        logger.warning("模型种子文件不存在: %s", SEED_FILE)
        return 0

    existing_models = {item.model_name: item for item in db.query(ModelCatalog).all()}
    existing = set(existing_models)
    created = 0
    updated = 0
    with SEED_FILE.open("r", encoding="utf-8", newline="") as file:
        reader = csv.DictReader(file)
        for row in reader:
            model_name = row["model_name"].strip()
            if not model_name:
                continue
            reasoning_mode = (row.get("reasoning_mode") or "unsupported").strip()
            if model_name in existing:
                model = existing_models[model_name]
                if not model.is_custom and model.reasoning_mode != reasoning_mode:
                    model.reasoning_mode = reasoning_mode
                    updated += 1
                continue
            score_text = row.get("score") or ""
            db.add(
                ModelCatalog(
                    model_type=row["model_type"].strip(),
                    provider_name=row["provider_name"].strip(),
                    model_name=model_name,
                    reasoning_mode=reasoning_mode,
                    ability_tier=row["ability_tier"].strip(),
                    ability_category=row["ability_category"].strip(),
                    original_category=(row.get("original_category") or "").strip(),
                    core_features=(row.get("core_features") or "").strip(),
                    scenarios=(row.get("scenarios") or "").strip(),
                    score=float(score_text) if score_text else None,
                    score_label=(row.get("score_label") or "").strip(),
                    enabled=True,
                    is_custom=False,
                )
            )
            existing.add(model_name)
            created += 1
    if created or updated:
        db.commit()
        logger.info("模型清单初始化完成，新增 %d 个模型，更新 %d 个模型", created, updated)
    return created
