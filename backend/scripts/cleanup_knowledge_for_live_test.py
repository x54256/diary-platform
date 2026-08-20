"""清理目标日记的历史知识沉淀数据（本轮实测前重置）。

先列出各表将删除的行数，再执行删除。仅操作指定 diary_id。
"""

import json
from uuid import UUID

from sqlalchemy import text

from database import SessionLocal

DIARY_ID = UUID("567d5606-f5f4-49c6-9d57-933bb72045a9")


def main() -> None:
    db = SessionLocal()
    try:
        task_ids = [
            row[0]
            for row in db.execute(
                text("SELECT id FROM knowledge_tasks WHERE diary_id = :did"),
                {"did": DIARY_ID},
            ).fetchall()
        ]

        counts = {}
        counts["knowledge_tasks"] = len(task_ids)
        counts["knowledge_deposits"] = db.execute(
            text("SELECT COUNT(*) FROM knowledge_deposits WHERE diary_id = :did"),
            {"did": DIARY_ID},
        ).scalar_one()
        counts["knowledge_atomic_events"] = db.execute(
            text("SELECT COUNT(*) FROM knowledge_atomic_events WHERE diary_id = :did"),
            {"did": DIARY_ID},
        ).scalar_one()
        counts["knowledge_event_reviews"] = db.execute(
            text(
                "SELECT COUNT(*) FROM knowledge_event_reviews r "
                "JOIN knowledge_atomic_events e ON e.id = r.knowledge_event_id "
                "WHERE e.diary_id = :did"
            ),
            {"did": DIARY_ID},
        ).scalar_one()

        checkpoint_counts = {}
        for table in ("checkpoints", "checkpoint_blobs", "checkpoint_writes"):
            try:
                n = db.execute(
                    text(f"SELECT COUNT(*) FROM {table} WHERE thread_id::uuid = ANY(:ids)"),
                    {"ids": task_ids},
                ).scalar_one()
            except Exception as exc:  # 表不存在或无匹配
                n = f"skip({exc.__class__.__name__})"
            checkpoint_counts[table] = n
        counts["checkpoint_tables"] = checkpoint_counts

        print("== before delete ==")
        print(json.dumps({"task_ids": [str(t) for t in task_ids], "counts": counts}, ensure_ascii=False))

        # 按外键依赖顺序删除
        del_reviews = db.execute(
            text(
                "DELETE FROM knowledge_event_reviews WHERE knowledge_event_id IN "
                "(SELECT id FROM knowledge_atomic_events WHERE diary_id = :did)"
            ),
            {"did": DIARY_ID},
        ).rowcount
        del_events = db.execute(
            text("DELETE FROM knowledge_atomic_events WHERE diary_id = :did"),
            {"did": DIARY_ID},
        ).rowcount
        del_deposits = db.execute(
            text("DELETE FROM knowledge_deposits WHERE diary_id = :did"),
            {"did": DIARY_ID},
        ).rowcount
        del_tasks = db.execute(
            text("DELETE FROM knowledge_tasks WHERE diary_id = :did"),
            {"did": DIARY_ID},
        ).rowcount

        db.commit()
        print("== deleted knowledge tables ==")
        print(json.dumps({
            "deleted_reviews": del_reviews,
            "deleted_atomic_events": del_events,
            "deleted_deposits": del_deposits,
            "deleted_tasks": del_tasks,
        }, ensure_ascii=False))

        # checkpoint 单独事务，失败不影响上面的删除
        del_checkpoints = {}
        for table in ("checkpoint_writes", "checkpoint_blobs", "checkpoints"):
            try:
                n = db.execute(
                    text(f"DELETE FROM {table} WHERE thread_id::uuid = ANY(:ids)"),
                    {"ids": task_ids},
                ).rowcount
                db.commit()
            except Exception as exc:
                db.rollback()
                n = f"skip({exc.__class__.__name__})"
            del_checkpoints[table] = n

        print("== deleted checkpoints ==")
        print(json.dumps(del_checkpoints, ensure_ascii=False))
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    main()
