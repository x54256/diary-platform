#!/usr/bin/env python3
"""未分析日记的只读导出、预检和确认后入库；默认不写数据库。"""

import argparse
import json
import os
import sys
from datetime import date, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "shared"))
from skill_files import read_text
from uuid import UUID
from zoneinfo import ZoneInfo

from markdown_to_json import AnalysisInputError, DIARY_FIELDS, digest, file_digest, parse_markdown, read_export, write_json


def open_backend(path):
    backend = Path(path).resolve()
    if not (backend / "database.py").is_file():
        raise AnalysisInputError("backend 路径无效")
    os.chdir(backend)
    sys.path.insert(0, str(backend))
    from database import SessionLocal
    import models  # noqa: F401
    return SessionLocal


def today():
    return datetime.now(ZoneInfo("Asia/Shanghai")).date()


def json_list(value):
    if value is None:
        return []
    if isinstance(value, str):
        value = json.loads(value)
    if not isinstance(value, list) or any(not isinstance(s, str) for s in value):
        raise AnalysisInputError("结构化日记字段须为字符串数组")
    return value


def find_diaries(db, username, diary_date):
    from models.user import User
    from models.diary import AnalysisRun, Diary, DiaryStatus
    user = db.query(User).filter(User.username == username).one_or_none()
    if user is None:
        raise AnalysisInputError("指定用户不存在")
    rows = db.query(Diary).filter(Diary.user_id == user.id, Diary.diary_date == diary_date,
                                  Diary.deleted_at.is_(None)).order_by(Diary.id).all()
    candidates = []
    for row in rows:
        has_analysis = db.query(AnalysisRun.id).filter(AnalysisRun.diary_id == row.id).first() is not None
        candidates.append({"diary_id": str(row.id), "diary_date": row.diary_date.isoformat(),
                           "status": row.status.value, "has_analysis": has_analysis,
                           "eligible_status": row.status == DiaryStatus.organized and not has_analysis,
                           "event_count": len(row.organized.events) if row.organized else 0})
    return {"user_id": str(user.id), "match_count": len(candidates), "diaries": candidates}


def load_target(db, diary_id, user_id, *, lock=False):
    from models.user import User
    from models.diary import AnalysisRun, Diary, DiaryEvent, DiaryOrganized, DiaryStatus, OrganizeTask
    from models.graph import GraphTask
    # 与后台建图/分析入口使用相同用户锁，防止确认保存与任务创建交叉执行。
    if lock:
        db.query(User).filter(User.id == UUID(user_id)).with_for_update().one()
    query = db.query(Diary).filter(Diary.id == UUID(diary_id), Diary.user_id == UUID(user_id),
                                   Diary.deleted_at.is_(None))
    diary = (query.with_for_update() if lock else query).first()
    if diary is None:
        raise AnalysisInputError("日记不存在、已删除或不属于指定用户")
    if diary.status != DiaryStatus.organized or not diary.organized:
        raise AnalysisInputError("仅支持已整理且未分析的日记")
    if db.query(AnalysisRun.id).filter(AnalysisRun.diary_id == diary.id).first():
        raise AnalysisInputError("日记已有分析轮次，第一版不支持重分析")
    if diary.is_dirty or diary.organized.source_content_revision != diary.content_revision:
        raise AnalysisInputError("整理结果已过期，请先完成整理")
    if db.query(GraphTask.id).filter(GraphTask.user_id == diary.user_id,
                                    GraphTask.status.in_(("QUEUED", "RUNNING"))).first():
        raise AnalysisInputError("当前用户有运行中的建图或分析任务")
    if db.query(OrganizeTask.id).filter(OrganizeTask.diary_id == diary.id,
                                       OrganizeTask.status == "running").first():
        raise AnalysisInputError("日记有运行中的整理或分析任务")
    if lock:
        db.query(DiaryOrganized).filter(DiaryOrganized.id == diary.organized.id).with_for_update().one()
        db.query(DiaryEvent).filter(DiaryEvent.diary_organized_id == diary.organized.id).order_by(
            DiaryEvent.id).with_for_update().all()
    return diary


def build_export(db, diary, analysis_date=None):
    from services.person_relations import load_person_relation_context
    def columns(row):
        return {c.name: getattr(row, c.name) for c in row.__table__.columns}
    org = diary.organized
    records = sorted(org.events, key=lambda e: (e.sort_order, str(e.id)))
    events = [{"event_id": str(e.id), "title": e.event_title or "", "body": json_list(e.body),
               "feeling": json_list(e.feeling), "reflection": json_list(e.reflection),
               "importance": e.user_importance or e.ai_importance, "source_order": e.sort_order}
              for e in records]
    raw = {"diary": columns(diary), "organized": columns(org), "events": [columns(e) for e in records]}
    source = {"diary_id": str(diary.id), "user_id": str(diary.user_id),
              "diary_date": diary.diary_date.isoformat(), "organized_id": str(org.id),
              "structured_revision": org.structured_revision,
              "stored_sha256": digest(json.loads(json.dumps(raw, default=str)))}
    exported = {"schema_version": 1, "source": source,
                "structured_diary": {"diary_date": source["diary_date"],
                    "analysis_date": analysis_date or today().isoformat(), "timezone": "Asia/Shanghai",
                    "introduction": org.introduction or "", "events": events,
                    "trivia": json_list(org.trivia), "plans": json_list(org.plans)},
                "person_relations": load_person_relation_context(db, str(diary.user_id))}
    exported["export_sha256"] = digest(exported)
    return exported


def validate_backend_result(result):
    """使用项目日程模型作第二次校验，不静默丢弃字段或修改推荐值。"""
    from schemas.actions import ActionSchedulePayload
    for row in result["action_items"]:
        parsed = ActionSchedulePayload.model_validate(row["schedule"]).model_dump(mode="json")
        parsed.pop("title", None)
        if parsed != row["schedule"]:
            raise AnalysisInputError("推荐日程与后端规则不一致，请核对稿件")


def make_packet(markdown, source_path):
    exported = read_export(source_path)
    result = parse_markdown(read_text(markdown), exported)
    packet = {"schema_version": 1, "exported": exported,
              "markdown": {"path": str(Path(markdown).resolve()), "sha256": file_digest(markdown)},
              "source_file": {"path": str(Path(source_path).resolve()), "sha256": file_digest(source_path)},
              "result": result}
    packet["confirmation_sha256"] = digest(packet)
    return packet


def verify_packet(packet, confirmed=None):
    if not isinstance(packet, dict) or set(packet) != {
        "schema_version", "exported", "markdown", "source_file", "result", "confirmation_sha256"
    } or packet["schema_version"] != 1:
        raise AnalysisInputError("入库包格式错误")
    if digest({k: v for k, v in packet.items() if k != "confirmation_sha256"}) != packet["confirmation_sha256"]:
        raise AnalysisInputError("入库包已变化，请重新预检和确认")
    if confirmed is not None and confirmed != packet["confirmation_sha256"]:
        raise AnalysisInputError("确认指纹不匹配")
    for label in ("markdown", "source_file"):
        if file_digest(packet[label]["path"]) != packet[label]["sha256"]:
            raise AnalysisInputError("稿件或来源文件已变化，请重新预检和确认")
    rebuilt = make_packet(Path(packet["markdown"]["path"]), Path(packet["source_file"]["path"]))
    if rebuilt != packet:
        raise AnalysisInputError("稿件、来源和入库结果不一致")
    return packet["result"]


def assert_current(db, diary, exported):
    current = build_export(db, diary, exported["structured_diary"]["analysis_date"])
    if current != exported:
        raise AnalysisInputError("数据库来源或人物资料已变化，请重新导出、核对分析并确认")


def assert_fresh_dates(result):
    if any(date.fromisoformat(a["schedule"]["start_date"]) < today() for a in result["action_items"]):
        raise AnalysisInputError("推荐日期已早于当前上海日期，请修改稿件后重新预检和确认")


def persist_result(db, diary, result):
    """调用方持有事务与来源锁；按真实事件 ID 保存，不按标题或数组位置匹配。"""
    from models.diary import AnalysisRun, AnalysisItem, DiaryActionItem, DiaryStatus, OrganizeTask
    from services.action_items import apply_action_planning_result
    from services.search_indexing import refresh_changed_event_search_indexes, rebuild_event_keyword_segments
    from services.analysis_history import add_text_items, add_question_answer_items
    kind_by_field = {"emotion_analyses": "EMOTION", "behavior_decision_analyses": "BEHAVIOR_DECISION",
                     "self_understanding_analyses": "SELF_UNDERSTANDING", "action_suggestions": "ACTION_SUGGESTION",
                     "cognitive_calibration_analyses": "COGNITIVE_CALIBRATION",
                     "cognitive_enhancements": "COGNITIVE_ENHANCEMENT"}
    validate_backend_result(result)
    assert_fresh_dates(result)
    task = OrganizeTask(diary_id=diary.id, user_id=diary.user_id, task_type="analyze",
                        analysis_mode="ordinary", status="completed", current_step=None)
    db.add(task)
    db.flush()
    run = AnalysisRun(diary_id=diary.id, diary_organized_id=diary.organized.id,
                      source_structured_revision=diary.organized.structured_revision,
                      task_id=task.id, mood=diary.organized.mood or "", status="CURRENT")
    db.add(run)
    db.flush()
    # 第一版只首次分析，因此无需归档旧轮次、继承反馈或迁移旧批注。
    for field in DIARY_FIELDS:
        add_text_items(db, run.id, "DIARY", None, kind_by_field[field], result["diary_analysis"][field])
    for event in result["event_analyses"]:
        event_id = UUID(event["event_id"])
        for field in DIARY_FIELDS:
            add_text_items(db, run.id, "EVENT", event_id, kind_by_field[field], event[field])
        add_question_answer_items(db, run.id, "EVENT", event_id, event["question_answers"])
    db.flush()
    # 精确绑定本条建议，避免相同文本跨事件时误关联。
    saved = db.query(AnalysisItem).filter(AnalysisItem.analysis_run_id == run.id).all()
    suggestion_ids = {}
    import hashlib
    for index, event in enumerate(result["event_analyses"]):
        for text in event["action_suggestions"]:
            key = f"suggestion:event:{index}:{hashlib.sha256(text.encode()).hexdigest()[:12]}"
            suggestion_ids[key] = [str(i.id) for i in saved if i.analysis_type == "ACTION_SUGGESTION"
                                   and str(i.event_id) == event["event_id"] and i.content == text]
    for text in result["diary_analysis"]["action_suggestions"]:
        key = f"suggestion:diary:{hashlib.sha256(text.encode()).hexdigest()[:12]}"
        suggestion_ids[key] = [str(i.id) for i in saved if i.analysis_type == "ACTION_SUGGESTION"
                               and i.scope == "DIARY" and i.content == text]
    actions = [{**a, "analysis_item_ids": list(dict.fromkeys(
        identity for key in a["source_keys"] for identity in suggestion_ids.get(key, [])))}
        for a in result["action_items"]]
    created = apply_action_planning_result(db, diary.id, diary.user_id, run.id, actions)
    diary.status = DiaryStatus.analyzed
    db.flush()
    for event in result["event_analyses"]:
        event_id = UUID(event["event_id"])
        refresh_changed_event_search_indexes(db, event_id, include_event_content=False, include_analysis=True)
        # 只有情绪/行为分析时也须建立关键词；不能依赖语义层是否变化。
        rebuild_event_keyword_segments(db, event_id)
    # 读回验证保存的完整分析，失败即由调用方事务回滚。
    expected = []
    for scope, event_id, row in [("DIARY", None, result["diary_analysis"])] + [
            ("EVENT", e["event_id"], e) for e in result["event_analyses"]]:
        for field in DIARY_FIELDS:
            expected.extend((scope, event_id, kind_by_field[field], None, text, pos)
                            for pos, text in enumerate(row[field]))
        expected.extend((scope, event_id, "QUESTION_ANSWER", qa["question"], qa["answer"], pos)
                        for pos, qa in enumerate(row.get("question_answers", [])))
    actual = [(i.scope, str(i.event_id) if i.event_id else None, i.analysis_type, i.question, i.content, i.sort_order)
              for i in db.query(AnalysisItem).filter(AnalysisItem.analysis_run_id == run.id).populate_existing().all()]
    if sorted(map(repr, actual)) != sorted(map(repr, expected)):
        raise AnalysisInputError("分析入库读回不一致，停止提交")
    if len(created) != len(actions):
        raise AnalysisInputError("行动项入库数量不一致，停止提交")
    read_actions = db.query(DiaryActionItem).filter(DiaryActionItem.generation_run_id == run.id).order_by(
        DiaryActionItem.sort_order).populate_existing().all()
    if len(read_actions) != len(actions):
        raise AnalysisInputError("行动项入库读回数量不一致，停止提交")
    for actual_action, expected_action in zip(read_actions, actions):
        actual_schedule = {}
        for field in expected_action["schedule"]:
            value = getattr(actual_action, field)
            actual_schedule[field] = value.isoformat() if hasattr(value, "isoformat") else value
        if (actual_action.title != expected_action["title"] or actual_schedule != expected_action["schedule"] or
                actual_action.source_refs.get("source") != expected_action["source"] or
                actual_action.source_refs.get("analysis_item_ids") != expected_action["analysis_item_ids"]):
            raise AnalysisInputError("行动内容、日程或来源入库读回不一致，停止提交")
    return {"diary_id": str(diary.id), "analysis_run_id": str(run.id), "task_id": str(task.id),
            "events": len(result["event_analyses"]), "analysis_items": len(saved), "actions": len(created)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--backend-dir", type=Path, default=Path(__file__).resolve().parents[3] / "backend")
    sub = parser.add_subparsers(dest="command", required=True)
    find = sub.add_parser("find", help="按用户与日期只读列出日记候选")
    find.add_argument("--username", default="x5456")
    find.add_argument("--date", required=True, type=date.fromisoformat)
    export = sub.add_parser("export", help="只读导出结构化日记、人物资料和来源状态")
    export.add_argument("--diary-id", required=True)
    export.add_argument("--user-id", required=True)
    export.add_argument("--output", required=True, type=Path)
    prepare = sub.add_parser("prepare", help="只读预检并冻结待确认入库包")
    prepare.add_argument("--source", required=True, type=Path)
    prepare.add_argument("--markdown", required=True, type=Path)
    prepare.add_argument("--output", required=True, type=Path)
    save = sub.add_parser("save", help="默认只读核验；用户确认后用 --write 写库")
    save.add_argument("packet", type=Path)
    save.add_argument("--write", action="store_true")
    save.add_argument("--confirmed-sha256")
    args = parser.parse_args()
    from skill_api import maybe_remote
    maybe_remote("analyze", args)
    for key, value in vars(args).copy().items():
        if isinstance(value, Path):
            setattr(args, key, value.resolve())
    try:
        writing = args.command == "save" and args.write
        packet, exported = None, None
        if args.command in {"export", "prepare"} and args.output.exists():
            raise AnalysisInputError("输出文件已存在，请使用新的文件名")
        if args.command == "prepare":
            packet = make_packet(args.markdown, args.source)
            exported = packet["exported"]
        elif args.command == "save":
            if writing and not args.confirmed_sha256:
                raise AnalysisInputError("正式写库须获得整篇最终确认并传入对应指纹")
            packet = json.loads(args.packet.read_text(encoding="utf-8"))
            verify_packet(packet, args.confirmed_sha256)
            exported = packet["exported"]
        SessionLocal = open_backend(args.backend_dir)
        with SessionLocal() as db, db.begin():
            if not writing and db.bind.dialect.name == "postgresql":
                from sqlalchemy import text
                db.execute(text("SET TRANSACTION READ ONLY"))
            if args.command == "find":
                response = find_diaries(db, args.username, args.date)
            else:
                source = exported["source"] if exported else vars(args)
                diary = load_target(db, source["diary_id"], source["user_id"], lock=writing)
                if args.command == "export":
                    exported = build_export(db, diary)
                    response = {"status": "已只读导出", "path": str(args.output), "source": exported["source"]}
                else:
                    assert_current(db, diary, exported)
                    result = verify_packet(packet, args.confirmed_sha256 if writing else None)
                    validate_backend_result(result)
                    assert_fresh_dates(result)
                    if writing:
                        response = {"status": "已提交", **persist_result(db, diary, result)}
                    else:
                        response = {"status": "只读核验通过，未写库", "events": len(result["event_analyses"]),
                                    "actions": len(result["action_items"]),
                                    "confirmation_sha256": packet["confirmation_sha256"]}
        if args.command in {"export", "prepare"}:
            write_json(args.output, exported if args.command == "export" else packet)
        print(json.dumps(response, ensure_ascii=False))
    except AnalysisInputError as exc:
        parser.exit(1, f"操作停止：{exc}\n")
    except (ValueError, KeyError, TypeError, OSError):
        # 不回显异常消息：驱动/Pydantic 的异常可能含 SQL、正文或用户输入。
        parser.exit(1, "操作停止：请核对目标资格、来源和稿件格式、指纹及日期；未确认提交结果时先只读核对数据库\n")
    except Exception as exc:
        parser.exit(1, f"操作失败，异常类型：{type(exc).__name__}；先核对数据库状态，禁止盲目重试\n")


if __name__ == "__main__":
    main()
