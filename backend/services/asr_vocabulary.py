"""将用户维护的热词和人物名称同步到阿里云 ASR 热词表。"""

from __future__ import annotations

import hashlib
import json
import logging
from collections.abc import Iterable
from uuid import UUID

from sqlalchemy.orm import Session

from models.voice_profile import AsrVocabulary, HotWord, PersonRelation

logger = logging.getLogger("asr_vocabulary")

HOTWORD_WEIGHT = 4


def build_hotword_entries(db: Session, user_id: UUID) -> list[dict[str, object]]:
    """按当前资料构造完整词表，并按文本去重。"""
    values: list[str] = []
    values.extend(item.text.strip() for item in db.query(HotWord).filter(HotWord.user_id == user_id).all())
    for person in db.query(PersonRelation).filter(PersonRelation.user_id == user_id).all():
        values.append(person.name.strip())
        values.extend(str(name).strip() for name in (person.common_names or []))

    unique: dict[str, str] = {}
    for value in values:
        if value:
            unique.setdefault(value.casefold(), value)
    return [
        {"text": value, "weight": HOTWORD_WEIGHT, "lang": "zh"}
        for value in sorted(unique.values(), key=lambda item: (item.casefold(), item))
    ]


def hotword_fingerprint(entries: Iterable[dict[str, object]]) -> str:
    """生成与词表内容相关的稳定指纹。"""
    canonical = [
        {"text": str(item["text"]), "weight": int(item.get("weight", HOTWORD_WEIGHT)), "lang": item.get("lang", "zh")}
        for item in entries
    ]
    payload = json.dumps(canonical, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def load_vocabulary_state(db: Session, user_id: UUID) -> AsrVocabulary | None:
    return db.query(AsrVocabulary).filter(AsrVocabulary.user_id == user_id).first()


def save_vocabulary_state(
    db: Session,
    user_id: UUID,
    vocabulary_id: str | None,
    target_model: str,
    fingerprint: str,
) -> None:
    state = load_vocabulary_state(db, user_id)
    if state is None:
        state = AsrVocabulary(user_id=user_id)
        db.add(state)
    state.vocabulary_id = vocabulary_id
    state.target_model = target_model
    state.fingerprint = fingerprint
    db.commit()
    logger.info(
        "ASR 热词状态已保存 user_id=%s vocabulary_id=%s target_model=%s fingerprint=%s",
        user_id,
        vocabulary_id,
        target_model,
        fingerprint,
    )
