"""查询知识沉淀当前配置模型与该日记历史任务记录。"""

import json

from sqlalchemy import text

from database import SessionLocal

DIARY_ID = "567d5606-f5f4-49c6-9d57-933bb72045a9"


def main() -> None:
    db = SessionLocal()
    try:
        rows = db.execute(text(
            "SELECT m.model_name, c.name, s.setting_key, s.thinking_enabled "
            "FROM model_settings s "
            "LEFT JOIN channel_models cm ON cm.id = s.channel_model_id "
            "LEFT JOIN model_catalog m ON m.id = cm.model_id "
            "LEFT JOIN api_channels c ON c.id = cm.channel_id "
            "WHERE s.setting_key = 'knowledge'"
        )).fetchall()
        print(json.dumps(
            [{"model": r[0], "channel": r[1], "key": r[2], "thinking": r[3]} for r in rows],
            ensure_ascii=False,
        ))

        rows2 = db.execute(text(
            "SELECT status, error_code, started_at, completed_at, retry_count, created_at "
            "FROM knowledge_tasks WHERE diary_id = :did "
            "ORDER BY created_at DESC LIMIT 5"
        ), {"did": DIARY_ID}).fetchall()
        print(json.dumps(
            [{"status": r[0], "error_code": r[1], "started": str(r[2]), "completed": str(r[3]), "retry": r[4], "created": str(r[5])} for r in rows2],
            ensure_ascii=False,
        ))
    finally:
        db.close()


if __name__ == "__main__":
    main()
