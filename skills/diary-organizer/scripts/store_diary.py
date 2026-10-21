#!/usr/bin/env python3
"""项目内日记整理稿的只读预检与确认后入库。默认不写库。"""

import argparse
import json
import os
import sys
from datetime import date, datetime
from pathlib import Path
from uuid import UUID

from markdown_to_json import digest, file_digest, parse_markdown, validate_result


def open_backend(path):
    """在正确工作目录加载项目配置，不输出连接串或认证信息。"""
    backend = path.resolve()
    if not (backend / "database.py").is_file():
        raise ValueError("backend 路径无效")
    os.chdir(backend)
    sys.path.insert(0, str(backend))
    from database import SessionLocal
    import models  # noqa: F401：注册完整 ORM 关系
    return SessionLocal


def find_diaries(db, username, diary_date):
    """按用户及日记日期列出有效记录，不自动选择或修改日记。"""
    from sqlalchemy import func
    from models.user import User
    from models.diary import Diary, DiaryOrganized, DiaryEvent

    user = db.query(User.id, User.username).filter(User.username == username).one_or_none()
    if user is None:
        raise ValueError("指定用户不存在")
    event_count = (
        db.query(func.count(DiaryEvent.id))
        .join(DiaryOrganized, DiaryEvent.diary_organized_id == DiaryOrganized.id)
        .filter(DiaryOrganized.diary_id == Diary.id)
        .correlate(Diary).scalar_subquery()
    )
    rows = db.query(
        Diary.id, Diary.diary_date, Diary.status,
        func.length(Diary.original_text).label("original_length"), event_count.label("event_count"),
    ).filter(
        Diary.user_id == user.id, Diary.diary_date == diary_date, Diary.deleted_at.is_(None),
    ).order_by(Diary.id).all()
    return {
        "username": user.username, "user_id": str(user.id), "diary_date": diary_date.isoformat(),
        "match_count": len(rows),
        "diaries": [
            {"diary_id": str(row.id), "diary_date": row.diary_date.isoformat(),
             "status": row.status.value, "original_length": row.original_length,
             "event_count": row.event_count}
            for row in rows
        ],
    }


def load_source(db, diary_id, user_id, *, lock=False):
    """核实原文所属用户；读取不受整篇替换能力限制。"""
    from models.diary import Diary

    query = db.query(Diary).filter(Diary.id == UUID(diary_id), Diary.user_id == UUID(user_id),
                                   Diary.deleted_at.is_(None))
    diary = (query.with_for_update() if lock else query).first()
    if diary is None:
        raise ValueError("日记不存在、已删除或不属于指定用户")
    return diary


def assert_replaceable(db, diary):
    from models.diary import DiaryStatus, OrganizeTask
    from services.graph_tasks import assert_source_writable

    if diary.status not in (DiaryStatus.saved, DiaryStatus.organized):
        raise ValueError("仅已保存或已整理的日记可导入")
    assert_source_writable(db, diary.id, content=True)
    if db.query(OrganizeTask.id).filter(OrganizeTask.diary_id == diary.id,
                                       OrganizeTask.status == "running").first():
        raise ValueError("存在运行中的整理或分析任务")
    check_dependencies(db, diary)


def replacement_capability(db, diary):
    """只读报告整篇保存能力；不代表用户已经授权保存。"""
    from services.graph_runtime import GraphError

    try:
        assert_replaceable(db, diary)
    except (ValueError, GraphError) as exc:
        return {"can_replace": False, "reason": str(exc), "supports_event_patch": False}
    return {"can_replace": True, "reason": None, "supports_event_patch": False}


def load_target(db, diary_id, user_id, *, lock=False):
    from models.diary import DiaryEvent, DiaryOrganized

    diary = load_source(db, diary_id, user_id, lock=lock)
    assert_replaceable(db, diary)
    if lock:
        organized = db.query(DiaryOrganized).filter(DiaryOrganized.diary_id == diary.id).with_for_update().first()
        if organized:
            db.query(DiaryEvent).filter(DiaryEvent.diary_organized_id == organized.id).order_by(
                DiaryEvent.id).with_for_update().all()
    return diary


def check_dependencies(db, diary):
    """整篇替换不猜测旧、新事件映射，存在用户关联时停止。"""
    from models.diary import AnalysisRun, DiaryActionEventLink, DiaryAnnotation
    from models.favorite import Favorite
    from models.tag import EventTag

    if db.query(AnalysisRun.id).filter(AnalysisRun.diary_id == diary.id).first():
        raise ValueError("日记已有分析记录，不能整篇替换")
    if db.query(DiaryAnnotation.id).filter(DiaryAnnotation.diary_id == diary.id).first():
        raise ValueError("日记已有批注，不能整篇替换")
    events = list(diary.organized.events) if diary.organized else []
    ids = [event.id for event in events]
    if not ids:
        return
    related = (
        (Favorite, Favorite.event_id, "事件收藏"),
        (EventTag, EventTag.diary_event_id, "事件标签"),
        (DiaryActionEventLink, DiaryActionEventLink.diary_event_id, "行动项关联"),
    )
    for model, column, label in related:
        if db.query(model).filter(column.in_(ids)).first():
            raise ValueError(f"已有{label}，不能整篇替换")


def snapshot(diary):
    def columns(record):
        return {column.name: getattr(record, column.name) for column in record.__table__.columns}

    organized = diary.organized
    stored = {
        "diary": columns(diary),
        "organized": columns(organized) if organized else None,
        "events": [columns(event) for event in sorted(organized.events, key=lambda e: (e.sort_order, str(e.id)))]
                  if organized else [],
    }
    # 只保存指纹，正文仍保留在原日记和本地整理稿，不在上下文中复制数据库内容。
    stored_hash = digest(json.loads(json.dumps(stored, default=str)))
    return {
        "diary_id": str(diary.id), "user_id": str(diary.user_id),
        "diary_date": diary.diary_date.isoformat(), "content_revision": diary.content_revision,
        "original_sha256": digest(diary.original_text),
        "organized_id": str(organized.id) if organized else None,
        "structured_revision": organized.structured_revision if organized else None,
        "existing_events": len(organized.events) if organized else 0,
        "stored_sha256": stored_hash,
    }


def make_packet(markdown, clarifications, source):
    if markdown.parent != clarifications.parent:
        raise ValueError("澄清记录须与整理稿在同一目录")
    if not clarifications.read_text(encoding="utf-8").strip():
        raise ValueError("澄清记录不能为空；无提问时写明本次无需澄清")
    packet = {
        "schema_version": 1,
        "source": source,
        "markdown": {"path": str(markdown), "sha256": file_digest(markdown)},
        "clarifications": {"path": str(clarifications), "sha256": file_digest(clarifications)},
        "result": parse_markdown(markdown.read_text(encoding="utf-8")),
    }
    packet["confirmation_sha256"] = digest(packet)
    return packet


def verify_packet(packet, confirmed=None):
    if not isinstance(packet, dict) or set(packet) != {
        "schema_version", "source", "markdown", "clarifications", "result", "confirmation_sha256"
    } or packet["schema_version"] != 1:
        raise ValueError("入库包格式不正确")
    unsigned = {key: value for key, value in packet.items() if key != "confirmation_sha256"}
    if digest(unsigned) != packet["confirmation_sha256"]:
        raise ValueError("入库包已修改，须重新预检和确认")
    if confirmed is not None and confirmed != packet["confirmation_sha256"]:
        raise ValueError("确认指纹不匹配")
    validate_result(packet["result"])
    for key in ("markdown", "clarifications"):
        if file_digest(packet[key]["path"]) != packet[key]["sha256"]:
            raise ValueError("整理稿或澄清记录已修改，须重新预检和确认")
    regenerated = parse_markdown(Path(packet["markdown"]["path"]).read_text(encoding="utf-8"))
    if regenerated != packet["result"]:
        raise ValueError("整理稿与入库结果不一致")


def persist_result(db, diary, result):
    """调用方持有事务；一并写入整理、事件、任务与搜索索引。"""
    from models.diary import DiaryOrganized, DiaryEvent, DiaryStatus, OrganizeTask
    from services.search_indexing import refresh_changed_event_search_indexes
    from utils.diary_render import render_diary_to_markdown

    validate_result(result)
    task = OrganizeTask(diary_id=diary.id, user_id=diary.user_id, task_type="organize",
                        status="completed", current_step=None)
    db.add(task)
    db.flush()
    organized = diary.organized
    if organized is None:
        organized = DiaryOrganized(diary_id=diary.id, task_id=task.id,
                                   source_content_revision=diary.content_revision, structured_revision=1)
        db.add(organized)
    else:
        for event in list(organized.events):
            db.delete(event)
        for log in list(organized.check_logs) + list(organized.clean_check_logs):
            db.delete(log)
        organized.structured_revision += 1
        organized.task_id = task.id
        organized.source_content_revision = diary.content_revision
    organized.introduction = result["introduction"]
    organized.trivia = json.dumps(result["trivia"], ensure_ascii=False)
    organized.plans = json.dumps(result["plans"], ensure_ascii=False)
    organized.content = render_diary_to_markdown(
        result["events"], result["introduction"], result["trivia"], result["plans"])
    # 整理阶段不生成分析元数据，避免沿用与新正文不一致的旧值。
    organized.title = organized.summary = organized.location = ""
    organized.mood = None
    organized.organized_at = datetime.utcnow()
    db.flush()
    created = []
    for index, value in enumerate(result["events"]):
        event = DiaryEvent(
            diary_organized_id=organized.id, event_title=value["title"],
            body=json.dumps(value["body"], ensure_ascii=False),
            feeling=json.dumps(value["feeling"], ensure_ascii=False),
            reflection=json.dumps(value["reflection"], ensure_ascii=False),
            event_tags="{}", sort_order=index, ai_importance=value["importance"],
            ai_importance_reason=value["importance_reason"], importance_origin="DIARY_ORGANIZE",
            importance_updated_at=datetime.utcnow())
        db.add(event)
        created.append(event)
    diary.status = DiaryStatus.organized
    diary.is_dirty = False
    db.flush()
    for event in created:
        refresh_changed_event_search_indexes(db, event.id, include_event_content=True, include_analysis=False)
    saved = db.query(DiaryEvent).filter(DiaryEvent.diary_organized_id == organized.id).order_by(
        DiaryEvent.sort_order).populate_existing().all()
    actual = [{"title": e.event_title, "body": json.loads(e.body), "feeling": json.loads(e.feeling),
               "reflection": json.loads(e.reflection), "importance": e.ai_importance,
               "importance_reason": e.ai_importance_reason} for e in saved]
    if actual != result["events"]:
        raise ValueError("入库读回结果不一致，停止提交")
    return {"diary_id": str(diary.id), "organized_id": str(organized.id),
            "task_id": str(task.id), "events": len(created),
            "structured_revision": organized.structured_revision}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--backend-dir", type=Path, default=Path(__file__).resolve().parents[3] / "backend")
    commands = parser.add_subparsers(dest="command", required=True)
    find = commands.add_parser("find", help="按用户名和日记日期只读列出候选记录")
    find.add_argument("--username", default="x5456")
    find.add_argument("--date", required=True, type=date.fromisoformat, help="日记日期，YYYY-MM-DD")
    export = commands.add_parser("export", help="整理前只读导出原文并绑定来源状态")
    export.add_argument("--diary-id", required=True)
    export.add_argument("--user-id", required=True)
    export.add_argument("--output", required=True, type=Path)
    prepare = commands.add_parser("prepare", help="只读预检并生成待确认入库包")
    prepare.add_argument("--markdown", required=True, type=Path)
    prepare.add_argument("--clarifications", required=True, type=Path)
    prepare.add_argument("--source", required=True, type=Path)
    prepare.add_argument("--output", required=True, type=Path)
    save = commands.add_parser("save", help="默认只读核验；显式 --write 才提交")
    save.add_argument("packet", type=Path)
    save.add_argument("--write", action="store_true")
    save.add_argument("--confirmed-sha256")
    args = parser.parse_args()
    # 必须先解析本地绝对路径，再切换到 backend 加载 .env。
    for key, value in vars(args).copy().items():
        if isinstance(value, Path):
            setattr(args, key, value.resolve())
    try:
        if args.command == "find":
            SessionLocal = open_backend(args.backend_dir)
            with SessionLocal() as db, db.begin():
                if db.bind.dialect.name == "postgresql":
                    from sqlalchemy import text
                    db.execute(text("SET TRANSACTION READ ONLY"))
                matches = find_diaries(db, args.username, args.date)
            print(json.dumps(matches, ensure_ascii=False))
            return
        if args.command == "save":
            packet = json.loads(args.packet.read_text(encoding="utf-8"))
            if args.write and not args.confirmed_sha256:
                raise ValueError("正式写库须先获得用户确认并传入对应确认指纹")
            verify_packet(packet, args.confirmed_sha256)
            diary_id, user_id = packet["source"]["diary_id"], packet["source"]["user_id"]
        elif args.command == "prepare":
            if args.output.exists():
                raise ValueError("输出文件已存在，请使用新的入库包文件名")
            # 在访问数据库前校验本地资料，避免无效稿件发起数据库请求。
            make_packet(args.markdown, args.clarifications, {})
            exported = json.loads(args.source.read_text(encoding="utf-8"))
            if exported.get("schema_version") != 1 or digest(exported.get("original_text")) != exported["source"]["original_sha256"]:
                raise ValueError("原文导出文件格式不正确或已修改")
            diary_id, user_id = exported["source"]["diary_id"], exported["source"]["user_id"]
        else:
            if args.output.exists():
                raise ValueError("输出文件已存在，请使用新的原文导出文件名")
            diary_id, user_id = args.diary_id, args.user_id
        UUID(diary_id)
        UUID(user_id)
        SessionLocal = open_backend(args.backend_dir)
        writing = args.command == "save" and args.write
        with SessionLocal() as db, db.begin():
            if not writing and db.bind.dialect.name == "postgresql":
                from sqlalchemy import text
                db.execute(text("SET TRANSACTION READ ONLY"))
            diary = (load_source(db, diary_id, user_id) if args.command == "export"
                     else load_target(db, diary_id, user_id, lock=writing))
            source = snapshot(diary)
            if args.command == "export":
                exported = {"schema_version": 1, "source": source, "original_text": diary.original_text,
                            "capabilities": replacement_capability(db, diary)}
            elif args.command == "prepare":
                if source != exported["source"]:
                    raise ValueError("整理期间数据库来源已变化，请重新读取原文并核对整理稿")
                packet = make_packet(args.markdown, args.clarifications, source)
            else:
                if source != packet["source"]:
                    raise ValueError("数据库原文、日期或整理结果已变化，须重新预检和确认")
                if writing:
                    # 提交前再次核验本地文件；保存的是已校验的入库包结果。
                    verify_packet(packet, args.confirmed_sha256)
                    receipt = persist_result(db, diary, packet["result"])
        if args.command == "export":
            args.output.parent.mkdir(parents=True, exist_ok=True)
            with args.output.open("x", encoding="utf-8") as output:
                json.dump(exported, output, ensure_ascii=False, indent=2)
                output.write("\n")
            print(json.dumps({"status": "原文已只读导出", "path": str(args.output), "source": source,
                              "capabilities": exported["capabilities"]}, ensure_ascii=False))
        elif args.command == "prepare":
            with args.output.open("x", encoding="utf-8") as output:
                json.dump(packet, output, ensure_ascii=False, indent=2)
                output.write("\n")
            print(json.dumps({"status": "只读预检通过，未写入数据库；保存须有整篇最终确认", "packet": str(args.output),
                              "source": packet["source"], "new_events": len(packet["result"]["events"]),
                              "confirmation_sha256": packet["confirmation_sha256"]}, ensure_ascii=False))
        elif writing:
            print(json.dumps({"status": "已提交", **receipt}, ensure_ascii=False))
        else:
            print("只读核验通过，未写入数据库")
    except (ValueError, OSError) as exc:
        parser.exit(1, f"操作停止：{exc}\n")
    except Exception as exc:
        # 数据库异常可能含连接串、SQL 参数或正文，不直接输出异常文本。
        parser.exit(1, f"操作失败，异常类型：{type(exc).__name__}；请核对数据库状态后再重试\n")


if __name__ == "__main__":
    main()
