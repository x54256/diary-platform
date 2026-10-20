"""单日闭环和历史日期串行处理，正式结果只在发布阶段写入。"""

from uuid import UUID

from database import SessionLocal
from models.diary import Diary, DiaryStatus
from models.graph import GraphRun, utcnow
from services.graph_runtime import GraphContext, GraphError, digest
from services.graph_tasks import snapshot_for_task, source_material
from services.graph_points import extract_event
from services.graph_relations import embed_points, discover, identify
from services.graph_publish import publish


async def execute_task(task_id, token):
    while True:
        with SessionLocal() as db:
            from models.graph import GraphTask
            completed = db.query(GraphTask).filter(GraphTask.id == task_id).one()
            if completed.status == "SUCCEEDED": return
            ctx = GraphContext(task_id, None, token, completed.config_snapshot)
            task = ctx.owned(db, lock=True)
            run = db.query(GraphRun).filter(GraphRun.task_id == task.id,
                GraphRun.status.in_(("QUEUED", "RUNNING"))).order_by(GraphRun.diary_date, GraphRun.id).with_for_update().first()
            if not run:
                task.status, task.completed_at, task.updated_at = "SUCCEEDED", utcnow(), utcnow()
                db.commit(); return
            task.current_run_id = run.id
            ctx.run_id = run.id
            # 先持久化失败归属日期，来源准备失败也必须能够恢复。
            db.commit()
            task = ctx.owned(db, lock=True)
            run = db.query(GraphRun).filter(GraphRun.id == ctx.run_id).with_for_update().one()
            diary = db.query(Diary).filter(Diary.id == run.diary_id, Diary.user_id == task.user_id,
                Diary.deleted_at.is_(None)).with_for_update().first()
            if not diary: raise GraphError("SOURCE_CHANGED", "日期清单中的日记已不存在")
            if task.entry_type == "HISTORY" and not run.source_snapshot:
                existing = db.query(GraphRun.id).filter(GraphRun.diary_id == diary.id, GraphRun.status == "PUBLISHED").first()
                reason = "ALREADY_PUBLISHED" if existing else "NOT_ANALYZED" if (diary.status != DiaryStatus.analyzed and not (task.config_snapshot.get("graph_only") and diary.status == DiaryStatus.organized)) else None
                if reason:
                    run.status, run.skip_reason, run.updated_at = "SKIPPED", reason, utcnow()
                    db.commit(); continue
            if not run.source_snapshot:
                source = snapshot_for_task(db, diary, task)
                run.source_snapshot, run.source_sha256 = source, digest(source_material(source))
                run.source_organized_id = diary.organized.id
                run.analysis_run_id = UUID(source["previous_run_id"]) if task.entry_type == "HISTORY" and source["previous_run_id"] else None
            else: source = run.source_snapshot
            run.status, run.current_step, run.updated_at = "RUNNING", "PREPARE_SOURCE", utcnow()
            state = dict(run.checkpoint or {})
            if "point_work" not in state: state["point_work"] = {}
            run.checkpoint = state
            db.commit()
        for event in source["events"]:
            if event["importance"] not in ("MEDIUM", "HIGH"): continue
            if state["point_work"].get(event["event_id"], {}).get("passed"): continue
            state = await extract_event(ctx, event, state)
        state = await embed_points(ctx, state)
        if "pairs" not in state: state = await discover(ctx, source, state)
        if not state.get("graph_checked"): state = await identify(ctx, state)
        with SessionLocal() as db: entry_type = ctx.owned(db).entry_type
        if entry_type == "ANALYSIS":
            from services.graph_analysis import analyze
            state = await analyze(ctx, source, state)
        ctx.save("PUBLISH")
        publish(ctx, source, state)
