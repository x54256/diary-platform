"""仅在显式指定的本机隔离数据库运行，验证真实事务和证据外键。"""

import asyncio
import copy
import json
import os
import unittest
from datetime import date, timedelta
from unittest.mock import patch
from uuid import uuid4

from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from database import Base
import models
from models.diary import Diary, DiaryEvent, DiaryOrganized, DiaryStatus, AnalysisRun, OrganizeTask
from models.graph import GraphTask, GraphRun, GraphEventPoint, GraphEventRelation, GraphRelationEvidence, GraphModelCall, utcnow
from models.user import User
from services.graph_runtime import GraphContext, GraphError
from services.graph_tasks import create_analysis, create_history, graph_task_manager, retry_task
from services.graph_workflow import execute_task
from services.graph_points import source_units
from routers.graph import graph_result

TEST_URL = os.environ.get("GRAPH_TEST_DATABASE_URL")


@unittest.skipUnless(TEST_URL, "需显式指定本机隔离图谱测试数据库")
class GraphDatabaseTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        url = make_url(TEST_URL)
        if url.host != "127.0.0.1" or url.port != 55439 or url.database != "graph_test":
            raise RuntimeError("拒绝在非本次隔离数据库运行清理型测试")
        cls.engine = create_engine(url)
        with cls.engine.begin() as db: db.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        Base.metadata.create_all(cls.engine)
        cls.Session = sessionmaker(bind=cls.engine, expire_on_commit=False)

    def setUp(self):
        self.patches = [patch(m + ".SessionLocal", self.Session) for m in (
            "services.graph_tasks", "services.graph_runtime", "services.graph_publish", "services.graph_relations", "services.graph_workflow", "services.graph_points")]
        for p in self.patches: p.start()
        self.addCleanup(lambda: [p.stop() for p in self.patches])
        with self.engine.begin() as db:
            db.execute(text("TRUNCATE graph_relation_evidence,graph_event_relations,graph_event_points,graph_run_events,graph_model_calls,graph_runs,graph_tasks,analysis_runs,organize_tasks,diaries,users,model_settings,model_step_settings,channel_models,api_channels,model_catalog CASCADE"))
        with self.Session() as db:
            self.user = User(id=uuid4(), username="graph-verification", password_encrypted="隔离测试占位")
            db.add(self.user); db.commit()
        self.config = {"models": {}, "prompts": {"relation_a": "v4", "relation_b": "v4", "relation_c": "裁决"},
            "embedding_model": "隔离模型-v1", "min_similarity": 0.5, "top_k": 5,
            "context_limit": 65536, "max_output_tokens": 16384, "safety_tokens": 2048,
            "output_per_pair": 512, "embedding_max_chars": 8000}
        for role in ("relation_a", "relation_b", "relation_c"):
            self.config["models"][role] = {"model_name": "isolated-model"}
        self.calls = []

    def diary(self, day=1, analyzed=False, low=False):
        with self.Session() as db:
            d = Diary(id=uuid4(), user_id=self.user.id, original_text="隔离来源", diary_date=date(2026, 9, day), status=DiaryStatus.analyzed if analyzed else DiaryStatus.organized)
            db.add(d); db.flush()
            t = OrganizeTask(id=uuid4(), diary_id=d.id, user_id=self.user.id, status="completed", task_type="organize")
            db.add(t); db.flush()
            org = DiaryOrganized(id=uuid4(), task_id=t.id, diary_id=d.id, title="隔离日记", introduction="", trivia="[]", plans="[]")
            db.add(org); db.flush()
            e = DiaryEvent(id=uuid4(), diary_organized_id=org.id, event_title="同标题", body=json.dumps(["本日处理项目问题。"], ensure_ascii=False), feeling="[]", reflection="[]", ai_importance="LOW" if low else "HIGH", sort_order=0)
            db.add(e); db.flush()
            if analyzed: db.add(AnalysisRun(id=uuid4(), diary_id=d.id, diary_organized_id=org.id, task_id=t.id, status="CURRENT"))
            db.commit(); return d.id, e.id

    async def fake_call(self, ctx, role, unit_key, payload, validator, **kwargs):
        self.calls.append((role, payload))
        if role == "point_generate":
            result = {"title": payload["title"], "points": [{"no": 1, "summary": "处理问题", "detail": payload["paragraphs"][0]["text"]}]}
        elif role in ("point_combined", "point_review"):
            source, candidate = payload["source"], payload["candidate"]
            review = {"source_checks": [{"source_unit_id": x["id"], "comparison": "原文一致"} for x in source_units(source)],
                "checks": [{"no": p["no"], "summary_ok": True, "detail_ok": True, "issues": []} for p in candidate["points"]]}
            result = {"review": review, "candidate": candidate} if role == "point_combined" else review
        elif role == "embedding": result = {"data": [{"index": 0, "embedding": [1.0] + [0.0] * 1023}]}
        elif role.startswith("relation_"):
            pairs = payload.get("pairs") or [r["pair"] for r in payload["disagreements"]]
            events = {e["id"]: e for e in payload["events"]}; results = []
            for pair in pairs:
                if role == "relation_a":
                    results.append({"pair_id": pair["pair_id"], "status": "NO_RELATION", "reason": "首次判断", "relation": None})
                else:
                    ends = sorted((events[pair["event_a_id"]], events[pair["event_b_id"]]), key=lambda e: e["diary_date"])
                    results.append({"pair_id": pair["pair_id"], "status": "RELATED", "reason": "明确推进", "relation": {
                        "source_event_id": ends[0]["id"], "target_event_id": ends[1]["id"], "relation_type": "后续事件",
                        "certainty": "EXPLICIT", "source_point_nos": [1], "target_point_nos": [1], "description": "继续处理同一事项"}})
            result = {"results": results}
        elif role == "mood_tag_extract":
            result = {"title": "隔离标题", "summary": "隔离摘要", "location": "", "mood": "平静", "event_tags": [
                {"event_id": e["event_id"], "title": e["title"], "tags": {k: [] for k in ("domain", "topic", "person_object", "psychological", "knowledge")}} for e in payload["structured_diary"]["events"]]}
        elif role in ("core_analysis", "cognition_analysis"):
            events = payload.get("events") or payload["structured_diary"]["events"]
            fields = ("emotion_analyses", "behavior_decision_analyses", "self_understanding_analyses", "action_suggestions") if role == "core_analysis" else ("cognitive_calibration_analyses", "question_answers", "cognitive_enhancements")
            result = {"event_analyses": [{"event_id": e["event_id"], "title": e["title"], **{f: [] for f in fields}} for e in events], "diary_analysis": {f: [] for f in fields if f != "question_answers"}}
        elif role == "action_planning": result = {"action_items": []}
        else: raise AssertionError(role)
        validator(result); return result

    def run_task(self, task_id, fail_stage=None):
        async def call(ctx, role, unit_key, payload, validator, **kwargs):
            if role == fail_stage: raise GraphError("MODEL_CALL_FAILED", "隔离注入失败")
            return await self.fake_call(ctx, role, unit_key, payload, validator, **kwargs)
        with patch.object(GraphContext, "call", call):
            claimed = graph_task_manager.claim()
            self.assertEqual(claimed[0], task_id)
            asyncio.run(graph_task_manager.execute(*claimed))

    def new_analysis(self, diary_id):
        with self.Session() as db, patch("services.graph_tasks.freeze_config", return_value=self.config):
            return create_analysis(db, self.user.id, diary_id)[0].id

    def test_analysis_only_publishes_after_all_stages_and_obsoletes_old_run(self):
        diary_id, event_id = self.diary()
        task_id = self.new_analysis(diary_id); self.run_task(task_id)
        with self.Session() as db:
            task = db.get(GraphTask, task_id); self.assertEqual(task.status, "SUCCEEDED")
            first = db.query(GraphRun).filter(GraphRun.task_id == task_id).one()
            self.assertTrue(db.get(DiaryEvent, event_id).is_in_graph)
            self.assertIsNotNone(first.analysis_run_id)
            old_point = db.query(GraphEventPoint).filter(GraphEventPoint.run_id == first.id).one().id
        newer = self.new_analysis(diary_id)
        with self.Session() as db:
            self.assertEqual(db.get(GraphRun, first.id).status, "OBSOLETE")
            self.assertFalse(db.get(DiaryEvent, event_id).is_in_graph)
        self.run_task(newer)
        with self.Session() as db:
            self.assertEqual(db.query(GraphRun).filter(GraphRun.diary_id == diary_id, GraphRun.status == "PUBLISHED").count(), 1)
            self.assertIsNotNone(db.get(GraphEventPoint, old_point))

    def test_downstream_failure_has_no_formal_points_and_retry_reuses_graph(self):
        diary_id, _ = self.diary(); task_id = self.new_analysis(diary_id)
        self.run_task(task_id, "core_analysis")
        before = len([c for c in self.calls if c[0] == "point_generate"])
        with self.Session() as db:
            task = db.get(GraphTask, task_id); self.assertEqual(task.status, "FAILED")
            self.assertEqual(db.query(GraphEventPoint).count(), 0)
            self.assertEqual(db.get(Diary, diary_id).status, DiaryStatus.organized)
            retry_task(db, task)
        self.run_task(task_id)
        self.assertEqual(len([c for c in self.calls if c[0] == "point_generate"]), before)
        with self.Session() as db: self.assertEqual(db.get(GraphTask, task_id).status, "SUCCEEDED")

    def test_history_daily_publish_and_disagreement_correction(self):
        first, _ = self.diary(1, True); second, _ = self.diary(2, True)
        with self.Session() as db, patch("services.graph_tasks.freeze_config", return_value=self.config):
            old_analyses = {r.id for r in db.query(AnalysisRun)}
            task_id = create_history(db, self.user.id, date(2026, 9, 1), date(2026, 9, 2)).id
        self.run_task(task_id)
        with self.Session() as db:
            self.assertEqual(db.get(GraphTask, task_id).status, "SUCCEEDED")
            self.assertEqual({r.id for r in db.query(AnalysisRun)}, old_analyses)
            edge = db.query(GraphEventRelation).one()
            self.assertEqual(edge.final_source, "ADJUDICATED")
            self.assertEqual(db.query(GraphRelationEvidence).count(), 2)
            self.assertIn("disagreements", next(payload for role, payload in self.calls if role == "relation_c"))

    def test_empty_graph_and_unanalyzed_history_are_distinct(self):
        first, _ = self.diary(1, True, low=True); second, _ = self.diary(2, False)
        with self.Session() as db, patch("services.graph_tasks.freeze_config", return_value=self.config):
            task_id = create_history(db, self.user.id, date(2026, 9, 1), date(2026, 9, 2)).id
        self.run_task(task_id)
        with self.Session() as db:
            self.assertEqual(db.query(GraphEventPoint).count(), 0)
            self.assertEqual(db.query(GraphRun).filter(GraphRun.diary_id == first).one().status, "PUBLISHED")
            self.assertEqual(db.query(GraphRun).filter(GraphRun.diary_id == second).one().skip_reason, "NOT_ANALYZED")

    def test_source_change_rejects_failed_task_recovery(self):
        diary_id, event_id = self.diary(); task_id = self.new_analysis(diary_id)
        self.run_task(task_id, "core_analysis")
        with self.Session() as db:
            db.get(DiaryEvent, event_id).body = '["新来源。"]'; db.commit()
            with self.assertRaises(GraphError) as error: retry_task(db, db.get(GraphTask, task_id))
            self.assertEqual(error.exception.code, "SOURCE_CHANGED")

    def test_injected_publish_failure_rolls_back_points_and_analysis(self):
        diary_id, _ = self.diary(); task_id = self.new_analysis(diary_id)
        with patch("services.analysis_pipeline._save_analysis_result", side_effect=GraphError("PUBLISH_FAILED", "注入发布失败")):
            self.run_task(task_id)
        with self.Session() as db:
            self.assertEqual(db.query(GraphEventPoint).count(), 0)
            self.assertEqual(db.query(AnalysisRun).count(), 0)
            self.assertEqual(db.get(GraphTask, task_id).status, "FAILED")
            self.assertEqual(db.get(GraphTask, task_id).error_code, "PUBLISH_FAILED")

    def test_active_user_task_prevents_second_task(self):
        first, _ = self.diary(1); second, _ = self.diary(2)
        self.new_analysis(first)
        with self.assertRaises(GraphError) as error: self.new_analysis(second)
        self.assertEqual(error.exception.code, "USER_TASK_ACTIVE")

    def test_source_preparation_failure_retains_recoverable_date(self):
        diary_id, _ = self.diary(1, True)
        with self.Session() as db, patch("services.graph_tasks.freeze_config", return_value=self.config):
            task_id = create_history(db, self.user.id, date(2026, 9, 1), date(2026, 9, 1)).id
        with patch("services.graph_workflow.snapshot", side_effect=GraphError("SOURCE_NOT_READY", "来源准备失败")):
            self.run_task(task_id)
        with self.Session() as db:
            task = db.get(GraphTask, task_id)
            self.assertEqual(db.get(GraphRun, task.current_run_id).status, "FAILED")
            retry_task(db, task)
        self.run_task(task_id)
        with self.Session() as db: self.assertEqual(db.get(GraphTask, task_id).status, "SUCCEEDED")

    def test_expired_lease_reclaims_unknown_call_and_rejects_old_writer(self):
        diary_id, _ = self.diary(); task_id = self.new_analysis(diary_id)
        _, token = graph_task_manager.claim()
        with self.Session() as db:
            task = db.get(GraphTask, task_id)
            run = db.query(GraphRun).filter(GraphRun.task_id == task_id).one()
            task.lease_until = utcnow() - timedelta(seconds=1)
            db.add(GraphModelCall(task_id=task_id, run_id=run.id, stage="POINT_GENERATE", unit_key="old", attempt_no=1, status="STARTED", request_snapshot={}))
            db.commit(); run_id = run.id
        with self.assertRaises(GraphError): GraphContext(task_id, run_id, token, self.config).save()
        claimed = graph_task_manager.claim()
        self.assertEqual(claimed[0], task_id); self.assertNotEqual(claimed[1], token)
        with self.Session() as db: self.assertEqual(db.query(GraphModelCall).one().status, "UNKNOWN")

    def relation_context(self):
        diary_id, _ = self.diary(); task_id = self.new_analysis(diary_id)
        _, token = graph_task_manager.claim()
        with self.Session() as db: run_id = db.query(GraphRun).filter(GraphRun.task_id == task_id).one().id
        ctx = GraphContext(task_id, run_id, token, self.config)
        pairs = [{"pair_id": f"p{i}", "event_a_id": "a", "event_b_id": i} for i in "bcd"]
        state = {"event_pool": {i: {"id": i, "title": i, "points": [{"no": 1, "summary": i, "detail": i}]} for i in "abcd"}}
        return ctx, pairs, state

    def test_relation_partial_retry_preserves_good_result_and_records_extra(self):
        from services.graph_relations import judge
        ctx, pairs, state = self.relation_context(); pairs = pairs[:2]; seen = []
        async def call(_ctx, role, unit, payload, validator, **kw):
            seen.append([p["pair_id"] for p in payload["pairs"]])
            result = {"results": [{"pair_id": payload["pairs"][0]["pair_id"], "status": "NO_RELATION", "reason": "无关系", "relation": None}]}
            if len(seen) == 1: result["results"].append({"pair_id": "extra"})
            validator(result); return result
        with patch.object(GraphContext, "call", call): state = asyncio.run(judge(ctx, state, "relation_a", pairs))
        self.assertEqual(seen, [["pb", "pc"], ["pc"]])
        self.assertEqual(set(state["relation_a"]), {"pb", "pc"})
        self.assertEqual(state["relation_diagnostics"][0]["errors"][0]["code"], "EXTRA_PAIR")

    def test_truncated_relation_batch_splits_once(self):
        from services.graph_relations import judge
        ctx, pairs, state = self.relation_context(); seen = []
        async def call(_ctx, role, unit, payload, validator, **kw):
            seen.append(len(payload["pairs"]))
            if len(seen) == 1: raise GraphError("MODEL_OUTPUT_TRUNCATED", "输出截断")
            return {"results": [{"pair_id": p["pair_id"], "status": "NO_RELATION", "reason": "无关系", "relation": None} for p in payload["pairs"]]}
        with patch.object(GraphContext, "call", call): state = asyncio.run(judge(ctx, state, "relation_a", pairs))
        self.assertEqual(seen, [3, 2, 1]); self.assertEqual(len(state["relation_a"]), 3)

    def test_relation_c_supplement_reports_missing_reason(self):
        from services.graph_relations import judge
        ctx, pairs, state = self.relation_context(); pairs = pairs[:1]; seen = []
        pair_id = pairs[0]["pair_id"]
        candidates = {pair_id: [{}, {}]}
        async def call(_ctx, role, unit, payload, validator, **kw):
            seen.append(copy.deepcopy(payload))
            row = {"pair_id": pair_id, "status": "NO_RELATION", "relation": None}
            if len(seen) == 2: row["reason"] = "没有具体事项联系"
            result = {"results": [row]}; validator(result); return result
        with patch.object(GraphContext, "call", call):
            state = asyncio.run(judge(ctx, state, "relation_c", pairs, candidates))
        self.assertEqual(len(seen), 2)
        self.assertNotIn("validation_errors", seen[0])
        self.assertIn("reason", seen[1]["validation_errors"][0]["message"])
        self.assertIn("disagreements", seen[1])
        self.assertNotIn("pairs", seen[1])
        self.assertEqual(state["relation_c"][pair_id]["status"], "NO_RELATION")

    def test_runtime_keeps_raw_response_and_replays_success(self):
        import httpx
        from unittest.mock import AsyncMock
        ctx, _, _ = self.relation_context(); ctx.config = copy.deepcopy(self.config)
        ctx.config["models"]["relation_a"] = {"model_name": "isolated-model", "thinking_payload": {"enable_thinking": True}}
        envelope = {"choices": [{"message": {"content": '{"results":[]}', "reasoning_content": "保留思考"}, "finish_reason": "stop"}], "usage": {"prompt_tokens": 11, "completion_tokens": 22, "completion_tokens_details": {"reasoning_tokens": 5}}}
        post = AsyncMock(return_value=httpx.Response(200, json=envelope))
        with patch("services.graph_runtime.thaw_model", return_value=("https://example.invalid/v1", "isolated-key")), patch("httpx.AsyncClient.post", post):
            for _ in range(2): self.assertEqual(asyncio.run(ctx.call("relation_a", "one", {}, lambda r: self.assertEqual(r, {"results": []}))), {"results": []})
        self.assertEqual(post.await_count, 1)
        self.assertTrue(post.call_args.kwargs["json"]["enable_thinking"])
        with self.Session() as db:
            record = db.query(GraphModelCall).one()
            self.assertEqual(json.loads(record.response_text), envelope)
            self.assertEqual(record.reasoning_tokens, 5)
            self.assertNotIn("isolated-key", json.dumps(record.request_snapshot))

    def test_unexpected_failure_records_location_without_exception_message(self):
        from unittest.mock import AsyncMock
        diary_id, _ = self.diary()
        task_id = self.new_analysis(diary_id)
        failure = AsyncMock(side_effect=AttributeError("验收凭据不得写入诊断"))
        with self.Session() as db:
            run_id = db.query(GraphRun).filter(GraphRun.task_id == task_id).one().id
            db.get(GraphTask, task_id).current_run_id = run_id
            db.add(GraphModelCall(task_id=task_id, run_id=run_id, stage="POINT_GENERATE",
                unit_key="interrupted", attempt_no=1, status="STARTED", request_snapshot={}))
            db.commit()
        with patch("services.graph_workflow.execute_task", failure):
            asyncio.run(graph_task_manager.execute(*graph_task_manager.claim()))
        with self.Session() as db:
            task = db.get(GraphTask, task_id)
            run = db.query(GraphRun).filter(GraphRun.task_id == task_id).one()
            context = run.checkpoint["error_context"]
            self.assertEqual(task.error_code, "EXECUTION_FAILED")
            self.assertEqual(context["exception_type"], "AttributeError")
            self.assertTrue(context["frames"])
            self.assertNotIn("验收凭据", json.dumps(context, ensure_ascii=False))
            self.assertEqual(db.query(GraphModelCall).one().status, "UNKNOWN")

    def test_foreign_user_cannot_query_task_or_graph(self):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from database import get_db
        from routers.graph import router
        from services.auth import get_current_user
        diary_id, _ = self.diary(); task_id = self.new_analysis(diary_id)
        app = FastAPI(); app.include_router(router)
        def db_dep():
            with self.Session() as db: yield db
        app.dependency_overrides[get_db] = db_dep
        app.dependency_overrides[get_current_user] = lambda: User(id=uuid4(), username="另一个用户", password_encrypted="占位")
        with TestClient(app) as client:
            self.assertEqual(client.get(f"/api/graph/tasks/{task_id}").status_code, 404)
            self.assertEqual(client.get(f"/api/graph/diaries/{diary_id}").status_code, 404)
        app.dependency_overrides[get_current_user] = lambda: self.user
        with TestClient(app) as client:
            response = client.get(f"/api/graph/tasks/{task_id}")
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()["status"], "QUEUED")
            self.assertIn("/api/graph/history-build", client.get("/openapi.json").json()["paths"])

    def test_history_failure_stops_and_recovery_keeps_first_day(self):
        first, _ = self.diary(1, True); second, second_event = self.diary(2, True); third, _ = self.diary(3, True)
        with self.Session() as db, patch("services.graph_tasks.freeze_config", return_value=self.config):
            task_id = create_history(db, self.user.id, date(2026, 9, 1), date(2026, 9, 3)).id
        async def call(ctx, role, unit_key, payload, validator, **kwargs):
            if role == "point_generate" and unit_key == str(second_event): raise GraphError("MODEL_CALL_FAILED", "第二日失败", event_id=str(second_event))
            return await self.fake_call(ctx, role, unit_key, payload, validator, **kwargs)
        with patch.object(GraphContext, "call", call): asyncio.run(graph_task_manager.execute(*graph_task_manager.claim()))
        with self.Session() as db:
            runs = {r.diary_id: r for r in db.query(GraphRun)}
            self.assertEqual([runs[d].status for d in (first, second, third)], ["PUBLISHED", "FAILED", "QUEUED"])
            self.assertEqual(runs[second].checkpoint["error_context"]["event_id"], str(second_event))
            first_point = db.query(GraphEventPoint).filter(GraphEventPoint.run_id == runs[first].id).one().id
            retry_task(db, db.get(GraphTask, task_id))
        self.run_task(task_id)
        with self.Session() as db:
            self.assertEqual(db.get(GraphTask, task_id).status, "SUCCEEDED")
            self.assertIsNotNone(db.get(GraphEventPoint, first_point))

    def test_published_result_is_idempotent_and_evidence_side_is_enforced(self):
        from services.graph_publish import publish
        first, _ = self.diary(1, True); second, _ = self.diary(2, True)
        with self.Session() as db, patch("services.graph_tasks.freeze_config", return_value=self.config):
            task_id = create_history(db, self.user.id, date(2026, 9, 1), date(2026, 9, 2)).id
        self.run_task(task_id)
        with self.Session() as db:
            task = db.get(GraphTask, task_id); run = db.get(GraphRun, task.current_run_id)
            state, source, token, run_id = run.checkpoint, run.source_snapshot, task.run_token, run.id
            counts = (db.query(GraphEventPoint).count(), db.query(GraphEventRelation).count())
        publish(GraphContext(task_id, run_id, token, self.config), source, state)
        with self.Session() as db:
            self.assertEqual((db.query(GraphEventPoint).count(), db.query(GraphEventRelation).count()), counts)
            evidence = db.query(GraphRelationEvidence).filter(GraphRelationEvidence.side == "SOURCE").one()
            wrong = db.query(GraphEventPoint).filter(GraphEventPoint.event_id == evidence.target_event_id).one()
            evidence.point_id, evidence.point_run_id, evidence.point_event_id = wrong.id, wrong.run_id, wrong.event_id
            with self.assertRaises(IntegrityError): db.commit()
            db.rollback()

    def test_feedback_analysis_rebuilds_graph_and_only_rewrites_requested_blocks(self):
        from models.diary import AnalysisFeedback
        diary_id, event_id = self.diary(); first = self.new_analysis(diary_id); self.run_task(first)
        with self.Session() as db:
            previous = db.query(GraphRun).filter(GraphRun.task_id == first).one()
            db.add(AnalysisFeedback(analysis_run_id=previous.analysis_run_id, user_id=self.user.id, scope="EVENT",
                event_id=event_id, analysis_type="EMOTION", rating=2, comment="请重新分析情绪")); db.commit()
        start = len(self.calls); second = self.new_analysis(diary_id)
        async def call(ctx, role, unit_key, payload, validator, **kwargs):
            if role == "feedback_core_analysis":
                self.calls.append((role, payload))
                self.assertEqual(payload["structured_diary"]["events"][0]["body"], ["本日处理项目问题。"])
                result = {"rewrites": [{"scope": scope, "event_id": eid, "analysis_type": "EMOTION", "items": []}
                    for scope, eid in (("EVENT", str(event_id)), ("DIARY", None))]}
                validator(result); return result
            return await self.fake_call(ctx, role, unit_key, payload, validator, **kwargs)
        with patch.object(GraphContext, "call", call): asyncio.run(graph_task_manager.execute(*graph_task_manager.claim()))
        roles = [role for role, _ in self.calls[start:]]
        self.assertIn("point_generate", roles); self.assertIn("feedback_core_analysis", roles)
        self.assertNotIn("cognition_analysis", roles); self.assertNotIn("mood_tag_extract", roles)
        with self.Session() as db:
            self.assertEqual(db.get(GraphTask, second).status, "SUCCEEDED")
            self.assertEqual(db.query(GraphRun).filter(GraphRun.task_id == first).one().status, "OBSOLETE")

    def test_exact_recall_threshold_top_five_and_obsolete_exclusion(self):
        import math
        from services.graph_tasks import snapshot
        from services.graph_relations import recall
        ids = [self.diary(day, True) for day in range(1, 8)]
        with self.Session() as db, patch("services.graph_tasks.freeze_config", return_value=self.config):
            task_id = create_history(db, self.user.id, date(2026, 9, 1), date(2026, 9, 7)).id
        self.run_task(task_id)
        current_id, _ = self.diary(8); current_task = self.new_analysis(current_id)
        _, token = graph_task_manager.claim()
        with self.Session() as db:
            run = db.query(GraphRun).filter(GraphRun.task_id == current_task).one()
            source = run.source_snapshot; run_id = run.id
            low = db.query(GraphEventPoint).filter(GraphEventPoint.event_id == ids[0][1]).one()
            low.embedding = [0.4, math.sqrt(0.84)] + [0.0] * 1022
            db.commit()
        ctx = GraphContext(current_task, run_id, token, self.config)
        point_id = str(uuid4()); points = [{"id": point_id}]; vectors = {point_id: [1.0] + [0.0] * 1023}
        hits = recall(ctx, source, points, vectors)
        expected = sorted(str(eid) for _, eid in ids[1:])[:5]
        self.assertEqual([r["event_id"] for r in hits], expected)
        with self.Session() as db:
            obsolete = db.query(GraphRun).filter(GraphRun.diary_id == ids[1][0]).one()
            obsolete.status, obsolete.obsolete_at = "OBSOLETE", utcnow()
            deleted = db.get(Diary, ids[2][0]); deleted.deleted_at = utcnow(); db.commit()
        self.assertEqual(len(recall(ctx, source, points, vectors)), 4)
        with self.Session() as db:
            db.query(GraphEventPoint).filter(GraphEventPoint.event_id == ids[3][1]).one().embedding_model = "other-model"
            db.commit()
        with self.assertRaises(GraphError) as error: recall(ctx, source, points, vectors)
        self.assertEqual(error.exception.code, "EMBEDDING_NOT_READY")

    def test_quota_exhaustion_is_audited_without_structure_retry(self):
        import httpx
        from unittest.mock import AsyncMock
        ctx, _, _ = self.relation_context(); ctx.config = copy.deepcopy(self.config)
        ctx.config["models"]["relation_a"] = {"model_name": "isolated-model", "thinking_payload": {"enable_thinking": True}}
        envelope = {"error": {"code": "insufficient_quota", "message": "Free quota exhausted"}}
        post = AsyncMock(return_value=httpx.Response(403, json=envelope))
        with patch("services.graph_runtime.thaw_model", return_value=("https://example.invalid/v1", "isolated-key")), patch("httpx.AsyncClient.post", post):
            with self.assertRaises(GraphError) as error:
                asyncio.run(ctx.call("relation_a", "quota", {}, lambda r: None))
        self.assertEqual(error.exception.code, "MODEL_QUOTA_EXHAUSTED")
        self.assertEqual(post.await_count, 1)
        with self.Session() as db:
            record = db.query(GraphModelCall).one()
            self.assertEqual(record.error_code, "MODEL_QUOTA_EXHAUSTED")
            self.assertEqual(json.loads(record.response_text), envelope)
            self.assertEqual(db.get(GraphRun, ctx.run_id).current_step, "JUDGE_A")

    def test_relation_quota_exhaustion_does_not_start_supplementary_round(self):
        from services.graph_relations import judge
        from unittest.mock import AsyncMock
        ctx, pairs, state = self.relation_context()
        call = AsyncMock(side_effect=GraphError("MODEL_QUOTA_EXHAUSTED", "额度不足"))
        with patch.object(GraphContext, "call", call):
            with self.assertRaises(GraphError) as error:
                asyncio.run(judge(ctx, state, "relation_a", pairs))
        self.assertEqual(error.exception.code, "MODEL_QUOTA_EXHAUSTED")
        self.assertEqual(call.await_count, 1)

    def test_graph_vector_setting_is_independent_from_search_vector(self):
        from models.model_config import ApiChannel,ModelCatalog,ChannelModel,ModelSetting
        from services.graph_runtime import freeze_config
        def catalog(name,kind):
            return ModelCatalog(model_name=name,model_type=kind,provider_name="隔离",reasoning_mode="switchable" if kind=="language" else "unsupported",ability_tier="自定义",ability_category="通用对话" if kind=="language" else "文本向量化")
        with self.Session() as db:
            channel=ApiChannel(name="隔离模型渠道",api_base_url="https://example.invalid/v1",api_key_encrypted="隔离占位",thinkmode={"enabled":{"enable_thinking":True},"disabled":{"enable_thinking":False}})
            language=catalog("isolated-language","language");search=catalog("isolated-search","embedding");graph=catalog("qwen3.7-text-embedding-flash","embedding")
            db.add_all([channel,language,search,graph]);db.flush()
            bindings=[ChannelModel(channel_id=channel.id,model_id=m.id) for m in (language,search,graph)]
            db.add_all(bindings);db.flush()
            for key,binding,thinking in zip(("graph","embedding","graph_embedding"),bindings,(True,None,None)):
                db.add(ModelSetting(setting_key=key,channel_model_id=binding.id,thinking_enabled=thinking))
            db.commit();search_binding=bindings[1].id
        with patch("services.model_runtime.SessionLocal",self.Session), patch("services.model_runtime.decrypt_channel_key",return_value="isolated-key"):
            frozen=freeze_config()
        self.assertEqual(frozen["models"]["embedding"]["model_name"],"qwen3.7-text-embedding-flash")
        with self.Session() as db:self.assertEqual(db.query(ModelSetting).filter_by(setting_key="embedding").one().channel_model_id,search_binding)
