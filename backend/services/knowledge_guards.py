"""知识沉淀来源冻结守卫。调用方必须先锁定对应 Diary。"""

from uuid import UUID

from sqlalchemy.orm import Session

from models.knowledge import KnowledgeDeposit, KnowledgeTask


class KnowledgeSourceLockedError(RuntimeError):
    pass


def has_successful_deposit(db: Session, diary_id: UUID) -> bool:
    return db.query(KnowledgeDeposit.diary_id).filter(KnowledgeDeposit.diary_id == diary_id).first() is not None


def has_active_knowledge_task(db: Session, diary_id: UUID) -> bool:
    return db.query(KnowledgeTask.id).filter(
        KnowledgeTask.diary_id == diary_id,
        KnowledgeTask.status.in_(("QUEUED", "RUNNING")),
    ).first() is not None


def assert_knowledge_source_writable(db: Session, diary_id: UUID) -> None:
    if has_successful_deposit(db, diary_id):
        raise KnowledgeSourceLockedError("该日记已完成知识沉淀，结构化来源已锁定")
    if has_active_knowledge_task(db, diary_id):
        raise KnowledgeSourceLockedError("该日记正在进行知识沉淀，请等待任务完成")
