"""定时对账：扫描 chunk 缺失 / 不足 3 层（fact/self_understanding/cognition 不全）的事件并补算。

设计要点（见 §3.7 / 待明确 #4）：
- 在 best-effort enqueue 之上，周期性（如每日 cron）补偿因进程重启等未完成的遗漏。
- 由运维以 cron（或同等调度）触发；不引入 Celery 等新框架，复用现有脚本执行机制。
- 仅对「所属 diary 已 organized/analyzed 且未软删除」的事件做对账，保证与语义分支口径一致。

用法：
    python -m scripts.reconcile_event_embeddings
    python -m scripts.reconcile_event_embeddings 2        # 仅补算缺失（<2 层）的事件
"""

import logging
import sys

from sqlalchemy import func

from database import SessionLocal
from models.diary import Diary, DiaryEvent, DiaryOrganized, DiaryStatus, EventEmbeddingChunk
from services.embedding_sync import sync_event_embeddings

logger = logging.getLogger(__name__)


def reconcile(min_layers: int = 3) -> dict:
    """对账并补算 chunk 不足 min_layers 层的事件。

    Args:
        min_layers: 认为「完整」所需的最少层（默认 3，即 fact/self_understanding/cognition 齐全）。

    Returns:
        {"scanned": int, "reconciled": int}
    """
    db = SessionLocal()
    try:
        event_rows = (
            db.query(DiaryEvent.id)
            .join(DiaryOrganized, DiaryOrganized.id == DiaryEvent.diary_organized_id)
            .join(Diary, Diary.id == DiaryOrganized.diary_id)
            .filter(
                Diary.deleted_at.is_(None),
                Diary.status.in_(
                    [DiaryStatus.organized.value, DiaryStatus.analyzed.value]
                ),
            )
            .all()
        )
        event_ids = [row[0] for row in event_rows]
    finally:
        db.close()

    scanned = len(event_ids)
    reconciled = 0
    for eid in event_ids:
        db2 = SessionLocal()
        try:
            cnt = (
                db2.query(func.count(EventEmbeddingChunk.id))
                .filter(EventEmbeddingChunk.event_id == eid)
                .scalar()
                or 0
            )
        finally:
            db2.close()
        if cnt < min_layers:
            reconciled += 1
            try:
                sync_event_embeddings(eid, None)
            except Exception as exc:  # noqa: BLE001
                logger.warning("事件 %s 对账补算失败: %s", eid, exc)
    logger.info("对账完成：扫描 %d，需补算 %d", scanned, reconciled)
    return {"scanned": scanned, "reconciled": reconciled}


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    _min = int(sys.argv[1]) if len(sys.argv) > 1 else 3
    reconcile(min_layers=_min)
