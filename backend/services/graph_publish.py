"""正式图谱与日记分析在一个短事务中发布。"""

from uuid import UUID, uuid4

from database import SessionLocal
from models.diary import Diary, DiaryEvent, OrganizeTask, DiaryStatus
from models.graph import GraphEventPoint, GraphEventRelation, GraphRelationEvidence, GraphRun, GraphRunEvent, utcnow
from services.graph_runtime import GraphError, digest
from services.graph_relations import validate_pair, validate_vector
from services.graph_tasks import snapshot, source_material


def publish(ctx, source, state):
    with SessionLocal() as db:
        run = db.query(GraphRun).filter(GraphRun.id == ctx.run_id, GraphRun.task_id == ctx.task_id).first()
        if run and run.published_at is not None and run.status in ("PUBLISHED", "OBSOLETE"):
            return run.id
        task = ctx.owned(db, lock=True)
        run = db.query(GraphRun).filter(GraphRun.id == ctx.run_id, GraphRun.task_id == task.id).with_for_update().one()
        diary = db.query(Diary).filter(Diary.id == run.diary_id, Diary.user_id == task.user_id,
                                      Diary.deleted_at.is_(None)).with_for_update().first()
        if not diary: raise GraphError("SOURCE_CHANGED", "来源日记已不存在")
        fresh = snapshot(db, diary, analysis=task.entry_type == "ANALYSIS")
        if digest(source_material(fresh)) != run.source_sha256:
            raise GraphError("SOURCE_CHANGED", "来源内容已变化，禁止发布冻结候选")
        if not state.get("graph_checked"):
            raise GraphError("PAIR_RESULTS_INCOMPLETE", "图谱整体检查尚未完成")
        if task.entry_type == "ANALYSIS" and not state.get("actions_complete"):
            raise GraphError("ANALYSIS_INCOMPLETE", "后续分析尚未完成")
        events = state.get("event_pool", {})
        historic_ids = {UUID(e["run_id"]) for e in events.values() if e["run_id"] != str(ctx.run_id)}
        for run_id in sorted(historic_ids, key=str):
            history = db.query(GraphRun).filter(GraphRun.id == run_id, GraphRun.user_id == task.user_id,
                GraphRun.status == "PUBLISHED").with_for_update().first()
            if not history or history.diary_date >= run.diary_date:
                raise GraphError("DEPENDENCY_OBSOLETE", "历史关系证据运行已不可用")
            history_diary = db.query(Diary).filter(Diary.id == history.diary_id, Diary.deleted_at.is_(None)).first()
            if not history_diary: raise GraphError("DEPENDENCY_OBSOLETE", "历史来源日记已删除")
        point_lookup = {}
        for event in source["events"]:
            if event["importance"] not in ("MEDIUM", "HIGH"): continue
            event_id = UUID(event["event_id"])
            work = state.get("point_work", {}).get(event["event_id"])
            if not work or not work.get("passed") or not work.get("points"):
                raise GraphError("POINT_REVIEW_FAILED", "准入事件要点未完整通过核验")
            db.add(GraphRunEvent(run_id=run.id, event_id=event_id, user_id=task.user_id,
                                 source_order=event["source_order"]))
            db.flush()
            if [p["no"] for p in work["points"]] != list(range(1, len(work["points"]) + 1)):
                raise GraphError("MODEL_OUTPUT_INVALID", "要点序号不连续")
            for p in work["points"]:
                vector = state["vectors"].get(p["id"]); validate_vector(vector)
                db.add(GraphEventPoint(id=UUID(p["id"]), run_id=run.id, event_id=event_id,
                    user_id=task.user_id, no=p["no"], summary=p["summary"], detail=p["detail"],
                    embedding=vector, embedding_model=ctx.config["embedding_model"]))
                point_lookup[(event["event_id"], p["no"])] = p["id"]
            db.query(DiaryEvent).filter(DiaryEvent.id == event_id).update({"is_in_graph": True})
        db.flush()
        for event_id, event in events.items():
            if event["run_id"] != str(run.id):
                for point in event["points"]: point_lookup[(event_id, point["no"])] = point["id"]
        pairs = {p["pair_id"]: p for p in state.get("pairs", [])}
        final = state.get("final_pair_results", [])
        if len(final) != len(pairs) or {r["pair_id"] for r in final} != set(pairs):
            raise GraphError("PAIR_RESULTS_INCOMPLETE", "最终事件对结果覆盖不完整")
        for result in final:
            validate_pair({k: v for k, v in result.items() if k != "final_source"}, pairs[result["pair_id"]], events)
            if result["status"] != "RELATED": continue
            r = result["relation"]
            relation = GraphEventRelation(id=uuid4(), run_id=run.id, user_id=task.user_id,
                source_run_id=UUID(events[r["source_event_id"]]["run_id"]), source_event_id=UUID(r["source_event_id"]),
                target_run_id=UUID(events[r["target_event_id"]]["run_id"]), target_event_id=UUID(r["target_event_id"]),
                relation_type=r["relation_type"], certainty=r["certainty"], description=r["description"],
                final_source=result["final_source"])
            db.add(relation); db.flush()
            for side in ("source", "target"):
                for no in r[side + "_point_nos"]:
                    point_id = point_lookup[(r[side + "_event_id"], no)]
                    db.add(GraphRelationEvidence(relation_id=relation.id, side=side.upper(), point_id=UUID(point_id),
                        user_id=task.user_id, source_run_id=relation.source_run_id, source_event_id=relation.source_event_id,
                        target_run_id=relation.target_run_id, target_event_id=relation.target_event_id,
                        point_run_id=getattr(relation, side + "_run_id"), point_event_id=getattr(relation, side + "_event_id")))
        if task.entry_type == "ANALYSIS":
            from services.analysis_pipeline import _persist_tags, _save_analysis_result, _inherited_feedback_keys
            result = {**state["analysis_result"], "structured_diary": source["structured_diary"],
                "task_id": str(task.organize_task_id), "diary_id": str(diary.id),
                "user_id": str(task.user_id), "diary_organized_id": source["organized_id"]}
            _persist_tags(db, str(task.user_id), str(diary.id), source["organized_id"], result["event_tags"])
            analysis = _save_analysis_result(db, result, source["organized_id"],
                feedback_source_run_id=source.get("previous_run_id"),
                inherited_feedback_keys=_inherited_feedback_keys(source.get("feedback_context", [])))
            run.analysis_run_id = analysis.id
            diary.status = DiaryStatus.analyzed
            db.query(OrganizeTask).filter(OrganizeTask.id == task.organize_task_id).update(
                {"status": "completed", "current_step": None, "error_message": None})
            task.status, task.completed_at = "SUCCEEDED", utcnow()
        else:
            other = db.query(GraphRun.id).filter(GraphRun.task_id == task.id, GraphRun.id != run.id,
                GraphRun.status.in_(("QUEUED", "RUNNING", "FAILED"))).first()
            if not other: task.status, task.completed_at = "SUCCEEDED", utcnow()
        run.status, run.published_at, run.current_step, run.updated_at = "PUBLISHED", utcnow(), None, utcnow()
        run.checkpoint = {**state, "published": True, "published_run_id": str(run.id)}
        task.updated_at = utcnow()
        db.flush(); db.commit()
        return run.id
