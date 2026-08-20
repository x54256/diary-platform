"""提取本轮知识沉淀结果：任务状态、知识事件、复核 issues，并计算保留率。"""

import json
from uuid import UUID

from sqlalchemy import text

from database import SessionLocal

DIARY_ID = UUID("567d5606-f5f4-49c6-9d57-933bb72045a9")
TASK_ID = UUID("c2b96128-6d26-4107-9660-2e090404907a")

NOISE_WORDS = ["嗯", "啊", "呃", "就是说", "那个", "然后呢", "对了"]


def main() -> None:
    db = SessionLocal()
    try:
        task = db.execute(text(
            "SELECT status, current_step, retry_count, error_code, error_message, "
            "started_at, completed_at FROM knowledge_tasks WHERE id = :tid"
        ), {"tid": TASK_ID}).fetchone()
        print("== task ==")
        print(json.dumps({
            "status": task[0], "step": task[1], "retry_count": task[2],
            "error_code": task[3], "error_message": task[4],
            "started_at": str(task[5]), "completed_at": str(task[6]),
        }, ensure_ascii=False))

        rows = db.execute(text(
            "SELECT e.id, e.source_diary_event_id, e.source_order, e.title, e.content, "
            "e.occurred_on, e.occurred_time, r.issues, r.content_changed "
            "FROM knowledge_atomic_events e "
            "LEFT JOIN knowledge_event_reviews r ON r.knowledge_event_id = e.id "
            "WHERE e.diary_id = :did "
            "ORDER BY e.source_diary_event_id, e.source_order"
        ), {"did": DIARY_ID}).fetchall()
        print(f"== atomic_events: {len(rows)} ==")

        total_content = 0
        for row in rows:
            content = row[4]
            if isinstance(content, str):
                content = json.loads(content)
            joined = "".join(content)
            total_content += len(joined)
            issues = row[7]
            if isinstance(issues, str):
                issues = json.loads(issues)
            noise_hits = sorted({w for w in NOISE_WORDS if w in joined})
            print(json.dumps({
                "source_event_id": str(row[1]),
                "source_order": row[2],
                "title": row[3],
                "occurred_on": str(row[5]),
                "occurred_time": str(row[6]) if row[6] else None,
                "content_chars": len(joined),
                "content": content,
                "issues": issues,
                "content_changed": row[8],
                "noise_hits": noise_hits,
            }, ensure_ascii=False))

        body_rows = db.execute(text(
            "SELECT e.id, e.body FROM diary_events e "
            "JOIN diary_organized o ON o.id = e.diary_organized_id "
            "WHERE o.diary_id = :did"
        ), {"did": DIARY_ID}).fetchall()
        total_body = 0
        for r in body_rows:
            body = r[1]
            if isinstance(body, str):
                body = json.loads(body)
            total_body += sum(len(s) for s in body)

        original_text = db.execute(
            text("SELECT original_text FROM diaries WHERE id = :did"),
            {"did": DIARY_ID},
        ).scalar_one()

        print("== metrics ==")
        print(json.dumps({
            "total_content_chars": total_content,
            "total_event_body_chars": total_body,
            "total_diary_original_chars": len(original_text),
            "retention_vs_event_body": round(total_content / total_body * 100, 1),
            "retention_vs_original_text": round(total_content / len(original_text) * 100, 1),
        }, ensure_ascii=False))
    finally:
        db.close()


if __name__ == "__main__":
    main()
