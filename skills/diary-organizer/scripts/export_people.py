#!/usr/bin/env python3
"""只读导出指定用户的人物关系，供日记整理时校正名称与指代。"""

import argparse
import json
from pathlib import Path

from store_diary import open_backend


def export_people(db, username):
    from models.user import User
    from models.voice_profile import PersonRelation

    user = db.query(User.id, User.username).filter(User.username == username).one_or_none()
    if user is None:
        raise ValueError("指定用户不存在")
    people = db.query(PersonRelation).filter(PersonRelation.user_id == user.id).order_by(
        PersonRelation.name, PersonRelation.id
    ).all()
    return {
        "user_id": str(user.id),
        "username": user.username,
        "people": [
            {"id": str(person.id), "name": person.name,
             "common_names": person.common_names or [], "gender": person.gender,
             "relation": person.relation}
            for person in people
        ],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--username", default="x5456")
    parser.add_argument("--backend-dir", type=Path, default=Path(__file__).resolve().parents[3] / "backend")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    output = args.output.resolve()
    try:
        SessionLocal = open_backend(args.backend_dir)
        with SessionLocal() as db:
            from sqlalchemy import text

            db.execute(text("SET TRANSACTION READ ONLY"))
            result = export_people(db, args.username)
        output.parent.mkdir(parents=True, exist_ok=True)
        with output.open("x", encoding="utf-8") as stream:
            json.dump(result, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
        print(f"人物关系导出完成：{output}，共 {len(result['people'])} 人")
    except Exception as exc:
        # 不输出连接异常全文，避免泄露认证信息。
        reason = str(exc) if isinstance(exc, (ValueError, FileExistsError)) else type(exc).__name__
        parser.exit(1, f"导出停止：{reason}\n")


if __name__ == "__main__":
    main()
