"""隔离内存库运行真实建图状态机与发布事务，模型阶段使用替身。"""
import asyncio
import unittest
from datetime import date
from unittest.mock import patch, AsyncMock
from uuid import uuid4

from sqlalchemy import Column, JSON, MetaData, String, Table, Uuid, create_engine
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import sessionmaker, Session
from pgvector.sqlalchemy import Vector

from models.user import User
from models.diary import Diary, DiaryStatus, DiaryOrganized, DiaryEvent
from models.graph import GraphTask, GraphRun, GraphEventPoint, GraphRunEvent, GraphEventRelation, GraphRelationEvidence, GraphModelCall
from services.graph_tasks import create_history, graph_task_manager, can_retry_task, retry_task, snapshot, source_material
from services.graph_workflow import execute_task
from services.graph_runtime import GraphError, digest


class GraphOnlyTest(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine('sqlite:///:memory:')
        self.db = Session(self.engine)
        self.addCleanup(self.engine.dispose)
        self.addCleanup(self.db.close)
        from types import SimpleNamespace
        self.user = SimpleNamespace(id=uuid4())
        metadata = MetaData()
        for model in (User, DiaryOrganized, GraphTask, Diary, DiaryEvent, GraphRun, GraphEventPoint, GraphRunEvent, GraphEventRelation, GraphRelationEvidence, GraphModelCall):
            Table(model.__tablename__, metadata, *(Column(column.name,
                Uuid() if isinstance(column.type, UUID) else JSON() if isinstance(column.type, JSONB)
                else String() if isinstance(column.type, Vector) else column.type,
                primary_key=column.primary_key, nullable=True) for column in model.__table__.columns))
        metadata.create_all(self.engine)
        self.Session = sessionmaker(bind=self.engine, expire_on_commit=False)
        self.db.add(User(id=self.user.id, username='isolated', password_encrypted='placeholder'))
        self.db.commit()
        for name in ('graph_tasks', 'graph_runtime', 'graph_workflow', 'graph_publish'):
            mock = patch(f'services.{name}.SessionLocal', self.Session)
            mock.start(); self.addCleanup(mock.stop)
        for name, result in [('get_current_analysis_run', None), ('load_person_relation_context', [])]:
            mock = patch(f'services.graph_tasks.{name}', return_value=result)
            mock.start(); self.addCleanup(mock.stop)

    def source(self, status=DiaryStatus.organized):
        d = Diary(id=uuid4(), user_id=self.user.id, diary_date=date(2026, 8, 17), original_text='原始日记', status=status)
        org = DiaryOrganized(id=uuid4(), diary_id=d.id, task_id=uuid4(), title='原始标题', introduction='', trivia='[]', plans='[]')
        event = DiaryEvent(id=uuid4(), diary_organized_id=org.id, event_title='原始事件', body='["保留原始内容。"]', feeling='[]', reflection='[]', ai_importance='HIGH', sort_order=0)
        self.db.add_all([d, org, event]); self.db.commit()
        return d, event

    def test_graph_only_publishes_without_creating_analysis_or_changing_source_status(self):
        diary, event = self.source()
        saved, _ = self.source(DiaryStatus.saved)
        with patch('services.graph_tasks.freeze_config', return_value={'embedding_model': 'test'}):
            task = create_history(self.db, self.user.id, date(2026, 8, 17), date(2026, 8, 18), graph_only=True)
        self.assertEqual(self.db.query(GraphRun).filter(GraphRun.task_id == task.id).count(), 1)
        self.assertTrue(task.config_snapshot['graph_only'])
        token = graph_task_manager.claim()
        self.assertEqual(token[0], task.id)
        async def extract(ctx, source, state):
            state['point_work'][source['event_id']] = {'passed': True, 'points': [
                {'id': str(uuid4()), 'no': 1, 'summary': '保留内容', 'detail': '保留原始内容。'}]}
            return ctx.save(point_work=state['point_work'])
        async def embed(ctx, state):
            return ctx.save(vectors={point['id']: [1.0] + [0.0] * 1023
                for work in state['point_work'].values() for point in work['points']})
        async def discover(ctx, source, state): return ctx.save(event_pool={}, pairs=[])
        async def identify(ctx, state): return ctx.save(graph_checked=True, final_pair_results=[])
        downstream = AsyncMock(side_effect=AssertionError('仅建图不得执行后续分析'))
        with patch('services.graph_workflow.extract_event', extract), patch('services.graph_workflow.embed_points', embed), patch('services.graph_workflow.discover', discover), patch('services.graph_workflow.identify', identify), patch('services.graph_analysis.analyze', downstream):
            asyncio.run(execute_task(*token))
        self.db.expire_all()
        self.assertEqual(self.db.get(GraphTask, task.id).status, 'SUCCEEDED')
        run = self.db.query(GraphRun).filter(GraphRun.task_id == task.id).one()
        self.assertEqual(run.status, 'PUBLISHED')
        self.assertIsNone(run.analysis_run_id)
        self.assertEqual(self.db.get(Diary, diary.id).status, DiaryStatus.organized)
        self.assertEqual(self.db.get(Diary, saved.id).status, DiaryStatus.saved)
        self.assertEqual(self.db.get(DiaryEvent, event.id).body, '["保留原始内容。"]')
        self.assertTrue(self.db.get(DiaryEvent, event.id).is_in_graph)
        self.assertEqual(self.db.query(GraphEventPoint).filter(GraphEventPoint.run_id == run.id).count(), 1)
        downstream.assert_not_awaited()

    def test_original_history_still_requires_existing_analysis(self):
        diary, _ = self.source()
        from services.graph_tasks import snapshot
        with self.assertRaises(GraphError): snapshot(self.db, diary)
        self.assertIsNone(snapshot(self.db, diary, allow_unanalyzed=True)['previous_run_id'])

    def test_graph_only_failure_can_resume_without_analysis(self):
        diary, _ = self.source()
        with patch('services.graph_tasks.freeze_config', return_value={}):
            task = create_history(self.db, self.user.id, date(2026, 8, 17), date(2026, 8, 18), graph_only=True)
        run = self.db.query(GraphRun).filter(GraphRun.task_id == task.id).one()
        run.source_snapshot = snapshot(self.db, diary, allow_unanalyzed=True)
        run.source_sha256 = digest(source_material(run.source_snapshot))
        run.status = task.status = 'FAILED'
        self.db.commit()
        self.assertTrue(can_retry_task(self.db, task))
        retry_task(self.db, task)
        self.assertEqual(task.status, 'QUEUED')
        self.assertEqual(run.status, 'QUEUED')
        self.assertTrue(task.config_snapshot['graph_only'])

    def test_original_history_skips_organized_diary(self):
        self.source()
        with patch('services.graph_tasks.freeze_config', return_value={}):
            task = create_history(self.db, self.user.id, date(2026, 8, 17), date(2026, 8, 18))
        extract = AsyncMock(side_effect=AssertionError('原历史入口必须跳过未分析日记'))
        with patch('services.graph_workflow.extract_event', extract):
            asyncio.run(execute_task(*graph_task_manager.claim()))
        self.db.expire_all()
        run = self.db.query(GraphRun).filter(GraphRun.task_id == task.id).one()
        self.assertEqual(run.status, 'SKIPPED')
        self.assertEqual(run.skip_reason, 'NOT_ANALYZED')
        extract.assert_not_awaited()
