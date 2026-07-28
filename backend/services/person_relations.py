"""构造供 AI 流水线使用的人物关系上下文。"""

from uuid import UUID

from sqlalchemy.orm import Session

from models.voice_profile import PersonRelation


def load_person_relation_context(db: Session, user_id: str | UUID) -> list[dict[str, object]]:
    """读取当前用户的人物关系，并转换为不依赖 ORM 的提示词上下文。"""
    user_uuid = UUID(str(user_id)) if not isinstance(user_id, UUID) else user_id
    people = (
        db.query(PersonRelation)
        .filter(PersonRelation.user_id == user_uuid)
        .order_by(PersonRelation.created_at.asc())
        .all()
    )
    return [
        {
            "name": person.name,
            "common_names": list(person.common_names or []),
            "gender": person.gender,
            "relation": person.relation,
        }
        for person in people
    ]


def load_person_name_gender_context(db: Session, user_id: str | UUID) -> list[dict[str, object]]:
    """读取整理阶段所需的最小人物上下文：主名、常用名和性别。"""
    return [
        {
            "name": item["name"],
            "common_names": item["common_names"],
            "gender": item["gender"],
        }
        for item in load_person_relation_context(db, user_id)
    ]
