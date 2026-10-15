"""事件图谱迁移：只读预检或指定迁移执行，不输出连接与认证信息。"""

import argparse
import json
from pathlib import Path

from sqlalchemy import inspect, text

import models  # noqa: F401
from database import Base, engine

NEW_TABLES = ("graph_tasks", "graph_runs", "graph_model_calls", "graph_run_events",
              "graph_event_points", "graph_event_relations", "graph_relation_evidence")
OLD_TABLES = ("knowledge_event_reviews", "knowledge_atomic_events", "knowledge_deposits",
              "knowledge_tasks", "knowledge_matters")
OLD_KEYS = ("knowledge_event_extract", "knowledge_event_review", "knowledge_matter_assign", "knowledge_matter_overview")


def check(connection):
    inspector = inspect(connection)
    names = set(inspector.get_table_names())
    available = connection.execute(text("SELECT EXISTS(SELECT 1 FROM pg_available_extensions WHERE name='vector')")).scalar()
    duplicate_analysis = connection.execute(text("SELECT count(*) FROM (SELECT task_id FROM analysis_runs WHERE task_id IS NOT NULL GROUP BY task_id HAVING count(*)>1) d")).scalar()
    active_old = connection.execute(text("SELECT count(*) FROM knowledge_tasks WHERE status IN ('QUEUED','RUNNING')")).scalar() if "knowledge_tasks" in names else 0
    external = []
    for table in names - set(OLD_TABLES):
        for fk in inspector.get_foreign_keys(table):
            if fk["referred_table"] in OLD_TABLES: external.append({"table": table, "constraint": fk["name"]})
    missing = []
    migrated = all(t in names for t in NEW_TABLES)
    if migrated:
        for name in NEW_TABLES:
            table = Base.metadata.tables[name]
            columns = {c["name"]: c for c in inspector.get_columns(name)}
            for c in table.columns:
                actual = columns.get(c.name)
                if actual is None or actual["nullable"] != c.nullable:
                    missing.append(name + "." + c.name)
                elif c.comment != actual.get("comment"):
                    missing.append(name + "." + c.name + ":注释")
            actual_names = {x["name"] for x in inspector.get_foreign_keys(name)} | {x["name"] for x in inspector.get_unique_constraints(name)} | {x["name"] for x in inspector.get_check_constraints(name)} | {x["name"] for x in inspector.get_indexes(name)}
            expected_names = {c.name for c in table.constraints if c.name} | {i.name for i in table.indexes}
            missing.extend(name + ":" + n for n in sorted(expected_names - actual_names))
            foreign_keys = {fk["name"]: fk for fk in inspector.get_foreign_keys(name)}
            for expected in table.foreign_key_constraints:
                actual = foreign_keys.get(expected.name)
                if actual is None: continue
                if (actual.get("options", {}).get("ondelete") != expected.ondelete or
                    actual["constrained_columns"] != [e.parent.name for e in expected.elements] or
                    actual["referred_columns"] != [e.column.name for e in expected.elements] or
                    actual["referred_table"] != expected.referred_table.name):
                    missing.append(name + ":" + expected.name + ":外键定义")
        columns = {c["name"] for c in inspector.get_columns("diary_events")}
        if "is_in_graph" not in columns: missing.append("diary_events.is_in_graph")
        if "uq_analysis_runs_task" not in {i["name"] for i in inspector.get_indexes("analysis_runs")}: missing.append("analysis_runs:uq_analysis_runs_task")
        if str(next(c for c in inspector.get_columns("graph_event_points") if c["name"] == "embedding")["type"]) != "VECTOR(1024)": missing.append("graph_event_points.embedding:维度")
        missing.extend(sorted(names & set(OLD_TABLES)))
    elif names & set(NEW_TABLES):
        missing.append("部分图谱表已存在，禁止覆盖未核对结构")
    return {"migrated": migrated, "vector_available": bool(available),
        "duplicate_analysis_tasks": duplicate_analysis, "active_legacy_tasks": active_old,
        "external_legacy_references": external, "structure_errors": missing}


def configure_defaults(connection):
    # 只使用已存在且启用的渠道模型，不复制或改写认证数据。
    vector_id = connection.execute(text("""SELECT cm.id FROM channel_models cm
        JOIN model_catalog m ON m.id=cm.model_id JOIN api_channels c ON c.id=cm.channel_id
        WHERE cm.enabled AND m.enabled AND c.enabled AND m.model_type='embedding'
        AND m.model_name='qwen3.7-text-embedding-flash' ORDER BY c.created_at,cm.id LIMIT 1""")).scalar()
    if vector_id is not None:
        connection.execute(text("""INSERT INTO model_settings(id,setting_key,channel_model_id,thinking_enabled)
            VALUES(gen_random_uuid(),'graph_embedding',:model,NULL)
            ON CONFLICT(setting_key) DO NOTHING"""), {"model": vector_id})
    model_id = connection.execute(text("""SELECT cm.id FROM channel_models cm
        JOIN model_catalog m ON m.id=cm.model_id JOIN api_channels c ON c.id=cm.channel_id
        WHERE cm.enabled AND m.enabled AND c.enabled
        AND m.model_name IN ('qwen3.7-flash-2026-07-15','qwen3.7-flash')
        AND m.reasoning_mode IN ('switchable','always_on')
        AND jsonb_typeof(c.thinkmode->'enabled')='object'
        AND c.thinkmode->'enabled'<>'{}'::jsonb
        ORDER BY CASE m.model_name WHEN 'qwen3.7-flash-2026-07-15' THEN 0 ELSE 1 END,
                 c.created_at,cm.id LIMIT 1""")).scalar()
    if model_id is None: return
    for role in ("graph", "graph_point_generate", "graph_point_combined", "graph_point_review",
                 "graph_relation_a", "graph_relation_b", "graph_relation_c"):
        if role == "graph":
            connection.execute(text("""INSERT INTO model_settings(id,setting_key,channel_model_id,thinking_enabled)
                VALUES(gen_random_uuid(),:role,:model,true) ON CONFLICT(setting_key) DO NOTHING"""), {"role": role, "model": model_id})
        else:
            connection.execute(text("""INSERT INTO model_step_settings(id,step_key,channel_model_id,thinking_enabled)
                VALUES(gen_random_uuid(),:role,:model,true) ON CONFLICT(step_key) DO NOTHING"""), {"role": role, "model": model_id})


def apply(connection):
    report = check(connection)
    if report["structure_errors"]: raise RuntimeError("数据库已有结构不符合迁移前提")
    if report["migrated"]: return report
    if not report["vector_available"]: raise RuntimeError("数据库服务器缺少vector扩展，请先安装服务端依赖")
    if report["duplicate_analysis_tasks"] or report["active_legacy_tasks"] or report["external_legacy_references"]:
        raise RuntimeError("存在重复分析、活动旧任务或清单之外的外键，请先处理预检结果")
    connection.execute(text("SELECT pg_advisory_xact_lock(hashtext('diary:event_graph:migration'))"))
    inspector = inspect(connection)
    if inspector.has_table("knowledge_tasks"):
        ids = [str(i) for i in connection.execute(text("SELECT id FROM knowledge_tasks")).scalars()]
        for table in ("checkpoint_writes", "checkpoint_blobs", "checkpoints"):
            if inspector.has_table(table) and "thread_id" in {c["name"] for c in inspector.get_columns(table)}:
                connection.execute(text(f"DELETE FROM {table} WHERE thread_id=ANY(:ids)"), {"ids": ids})
    sql = (Path(__file__).resolve().parents[1] / "migrations/050_event_graph.sql").read_text()
    # 执行仓库内固定迁移，不接收SQL或连接串参数，不执行旧迁移。
    cursor = connection.connection.driver_connection.cursor()
    cursor.execute(sql)
    cursor.close()
    configure_defaults(connection)
    report = check(connection)
    if not report["migrated"] or report["structure_errors"]: raise RuntimeError("迁移后结构核验未通过")
    return report


def main():
    parser = argparse.ArgumentParser()
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--check", action="store_true")
    group.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    try:
        if args.apply:
            with engine.begin() as connection: report = apply(connection)
        else:
            with engine.connect() as connection: report = check(connection)
        print(json.dumps(report, ensure_ascii=False))
        return 0 if not report["structure_errors"] else 1
    except Exception as error:
        # 驱动异常会包含连接参数，禁止打印它们。
        message = str(error) if type(error) is RuntimeError else "数据库操作失败：" + type(error).__name__
        print(json.dumps({"error": message}, ensure_ascii=False)); return 1


if __name__ == "__main__": raise SystemExit(main())
