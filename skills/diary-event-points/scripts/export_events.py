#!/usr/bin/env python3
"""只读定位数据库日记，导出整理后事件到 Skill 的统一工作目录。"""

import argparse
from contextlib import contextmanager
from datetime import date, datetime, timezone
import hashlib
import json
import os
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "shared"))
import shutil
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo


SKILL_ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = SKILL_ROOT.parents[1]


class ExportError(Exception):
    """仅存放可向用户展示的脱敏错误。"""


def digest(value):
    return hashlib.sha256(json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")).hexdigest()


def workspace_root():
    settings = json.loads((SKILL_ROOT / "settings.json").read_text(encoding="utf-8"))
    value = settings.get("workspace_root")
    if not isinstance(value, str) or not value.strip():
        raise ExportError("Skill 工作目录配置缺失")
    return (SKILL_ROOT / value).resolve()


def json_array(value, field, *, required=False):
    if value is None and not required:
        return []
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except ValueError:
            raise ExportError(f"{field} 不是合法 JSON 数组") from None
    if not isinstance(value, list) or any(not isinstance(p, str) for p in value):
        raise ExportError(f"{field} 必须为字符串数组")
    if required and not any(p.strip() for p in value):
        raise ExportError(f"{field} 不能为空")
    return value


def query(connection, statement, params):
    from sqlalchemy import text
    return connection.execute(text(statement), params).mappings().all()


def list_diaries(connection, username, *, diary_date=None, diary_id=None):
    users = query(connection, "SELECT id FROM users WHERE username = :username",
                  {"username": username})
    if not users:
        raise ExportError("指定用户不存在")
    where = "d.user_id = :user_id AND d.deleted_at IS NULL"
    params = {"user_id": str(users[0]["id"])}
    if diary_date is not None:
        where += " AND d.diary_date = :diary_date"
        params["diary_date"] = diary_date.isoformat()
    if diary_id is not None:
        where += " AND d.id = :diary_id"
        params["diary_id"] = str(UUID(str(diary_id)))
    rows = query(connection, """
        SELECT d.id AS diary_id, d.diary_date, d.status, d.is_dirty, d.content_revision,
               o.id AS organized_id, o.source_content_revision, o.structured_revision,
               (SELECT count(*) FROM diary_events e WHERE e.diary_organized_id = o.id)
                   AS event_count
        FROM diaries d LEFT JOIN diary_organized o ON o.diary_id = d.id
        WHERE """ + where + " ORDER BY d.diary_date, d.id", params)
    return {"user_id": str(users[0]["id"]), "username": username,
            "match_count": len(rows), "diaries": [dict(r) for r in rows]}


def export_source(connection, username, *, diary_date=None, diary_id=None,
                  event_ids=()):
    listing = list_diaries(connection, username, diary_date=diary_date, diary_id=diary_id)
    if listing["match_count"] == 0:
        raise ExportError("未找到该用户的有效日记")
    if listing["match_count"] != 1:
        raise ExportError("该日期有多篇日记；请先 find，再用 --diary-id 指定一篇")
    diary = listing["diaries"][0]
    if diary["organized_id"] is None or diary["status"] not in ("organized", "analyzed"):
        raise ExportError("日记尚无有效整理结果")
    if diary["is_dirty"] or diary["source_content_revision"] != diary["content_revision"]:
        raise ExportError("整理结果已过期，请先完成日记整理")
    rows = query(connection, """
        SELECT id, event_title, body, feeling, reflection, sort_order,
               updated_at
        FROM diary_events WHERE diary_organized_id = :organized_id
        ORDER BY sort_order, id
    """, {"organized_id": str(diary["organized_id"])})
    requested = {str(UUID(str(i))) for i in event_ids}
    available = {str(r["id"]) for r in rows}
    if requested - available:
        raise ExportError("指定事件不属于本次日记或已不存在")
    events, excluded = [], []
    for row in rows:
        event_id = str(row["id"])
        if requested and event_id not in requested:
            excluded.append({"event_id": event_id, "reason": "not_selected"})
            continue
        events.append({
            "event_id": event_id, "title": row["event_title"] or "未命名事件",
            "body": json_array(row["body"], "事件正文", required=True),
            "feeling": json_array(row["feeling"], "感受"),
            "reflection": json_array(row["reflection"], "反思"),
            "source_order": row["sort_order"],
            "updated_at": str(row["updated_at"]) if row["updated_at"] is not None else None,
        })
    if not events:
        raise ExportError("当前选择范围内没有可提取事件")
    source = {
        "schema_version": 1, "origin": "database",
        "user_id": listing["user_id"], "username": username,
        "diary_id": str(diary["diary_id"]), "diary_date": str(diary["diary_date"]),
        "organized_id": str(diary["organized_id"]),
        "content_revision": diary["content_revision"],
        "structured_revision": diary["structured_revision"],
        "selection": {"event_ids": sorted(requested)},
        "events": events, "excluded_events": excluded,
    }
    source["source_sha256"] = digest(source)
    return source


def render_source(source):
    parts = [f"# {source['diary_date']} 数据库事件来源", "",
             f"日记 ID：`{source['diary_id']}`。本文件是 source.json 的阅读视图；"
             "标识和顺序仅为定位元数据，不作为经历内容。", ""]
    for event in source["events"]:
        parts += [f"## 事件：{event['title']}", "",
                  f"<!-- event_id: {event['event_id']} -->", "",
                  "\n\n".join(event["body"]), ""]
        for key, title in (("feeling", "感受"), ("reflection", "反思与成长")):
            if event[key]:
                parts += [f"### {title}", "", "\n\n".join(event[key]), ""]
    return "\n".join(parts).rstrip() + "\n"


def write_run(source, root=None):
    expected = source.get("source_sha256")
    if expected != digest({k: v for k, v in source.items() if k != "source_sha256"}):
        raise ExportError("来源指纹不匹配")
    # 路径组件只接受规范日期与 UUID，不把数据库中的标题或用户名拼进路径。
    day = date.fromisoformat(source["diary_date"]).isoformat()
    diary_id = str(UUID(source["diary_id"]))
    run_name = datetime.now(ZoneInfo("Asia/Shanghai")).strftime("%Y%m%dT%H%M%S") + "-" + uuid4().hex[:8]
    folder = (Path(root) if root is not None else workspace_root()) / day / diary_id / run_name
    folder.mkdir(parents=True, exist_ok=False)
    try:
        (folder / "source.json").write_text(
            json.dumps(source, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        (folder / "source.md").write_text(render_source(source), encoding="utf-8")
        manifest = {
            "schema_version": 1, "created_at": datetime.now(timezone.utc).isoformat(),
            "origin": "database", "diary_id": diary_id, "diary_date": day,
            "source_sha256": expected, "event_ids": [e["event_id"] for e in source["events"]],
            "event_count": len(source["events"]),
            "source_files_sha256": {name: hashlib.sha256((folder / name).read_bytes()).hexdigest()
                                    for name in ("source.json", "source.md")},
            "skill_files_sha256": {name: hashlib.sha256((SKILL_ROOT / name).read_bytes()).hexdigest()
                                   for name in ("SKILL.md", "references/examples.md", "settings.json")},
        }
        (folder / "run.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    except Exception:
        shutil.rmtree(folder)
        raise
    return folder


def load_engine(backend):
    backend = backend.resolve()
    if not (backend / "database.py").is_file():
        raise ExportError("backend 路径无效")
    previous = Path.cwd()
    try:
        os.chdir(backend)
        sys.path.insert(0, str(backend))
        from database import engine
        return engine
    finally:
        os.chdir(previous)


@contextmanager
def read_connection(engine):
    with engine.connect() as connection:
        if connection.dialect.name == "postgresql":
            connection = connection.execution_options(isolation_level="REPEATABLE READ")
            connection.exec_driver_sql("SET TRANSACTION READ ONLY")
        elif connection.dialect.name == "sqlite":
            connection.exec_driver_sql("PRAGMA query_only = ON")
        else:
            raise ExportError("当前数据库不支持本脚本的只读事务")
        try:
            yield connection
        finally:
            connection.rollback()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--backend-dir", type=Path, default=PROJECT_ROOT / "backend")
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("find", "export"):
        command = commands.add_parser(name)
        command.add_argument("--username", required=True)
        target = command.add_mutually_exclusive_group(required=True)
        target.add_argument("--date", type=date.fromisoformat)
        target.add_argument("--diary-id", type=UUID)
        if name == "export":
            command.add_argument("--event-id", type=UUID, action="append", default=[])
    args = parser.parse_args(argv)
    from skill_api import maybe_remote
    maybe_remote("points-source", args)
    try:
        with read_connection(load_engine(args.backend_dir)) as connection:
            kwargs = {"diary_date": args.date, "diary_id": args.diary_id}
            if args.command == "find":
                result = list_diaries(connection, args.username, **kwargs)
            else:
                source = export_source(connection, args.username, **kwargs,
                                       event_ids=args.event_id)
        if args.command == "export":
            folder = write_run(source)
            result = {"run_dir": str(folder), "events": len(source["events"]),
                      "excluded": len(source["excluded_events"]),
                      "source_sha256": source["source_sha256"]}
        print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
        return 0
    except ExportError as exc:
        print(f"导出停止：{exc}", file=sys.stderr)
    except Exception as exc:
        # SQLAlchemy 异常可能包含 SQL、参数和连接串，禁止回显异常全文。
        blocked = "Operation not permitted" in str(exc)
        reason = "运行环境拒绝网络访问，请按权限流程重试只读命令" if blocked else type(exc).__name__
        print(f"导出停止：{reason}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
