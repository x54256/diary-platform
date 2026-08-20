"""导出目标日记的 diary_events 原文（供实测对照），JSON 类型自适应解析。"""

import json
from uuid import UUID

from sqlalchemy import text

from database import SessionLocal

DIARY_ID = UUID("567d5606-f5f4-49c6-9d57-933bb72045a9")


def main() -> None:
    db = SessionLocal()
    try:
        diary = db.execute(
            text("SELECT id, original_text, diary_date, created_at FROM diaries WHERE id = :did"),
            {"did": DIARY_ID},
        ).fetchone()
        print("== diary ==")
        print(json.dumps({
            "id": str(diary[0]),
            "diary_date": str(diary[1]),
            "created_at": str(diary[3]),
            "original_text_len": len(diary[1] or ""),
            "original_text": diary[1],
        }, ensure_ascii=False))

        rows = db.execute(
            text(
                "SELECT e.id, e.event_title, e.body, e.feeling, e.reflection, e.sort_order "
                "FROM diary_events e "
                "JOIN diary_organized o ON o.id = e.diary_organized_id "
                "WHERE o.diary_id = :did ORDER BY e.sort_order, e.created_at, e.id"
            ),
            {"did": DIARY_ID},
        ).fetchall()
        print(f"== events: {len(rows)} ==")
        for i, row in enumerate(rows):
            print(json.dumps({
                "index": i,
                "event_id": str(row[0]),
                "event_title": row[1],
                "body": row[2],
                "feeling": row[3],
                "reflection": row[4],
            }, ensure_ascii=False))
    finally:
        db.close()


if __name__ == "__main__":
    main()
