"""隔离库验证要点及向量保存、来源保护、幂等与恢复；不访问项目库和外部模型。"""

import asyncio
from copy import deepcopy
from datetime import date
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch, AsyncMock
from uuid import uuid4

from store_points import (StorageError, digest, execute, file_digest, open_backend, parse_markdown,
                          prepare, readonly, status, submit, target, verify_packet)

PREVIOUS = Path.cwd()
open_backend(Path(__file__).resolve().parents[3] / 'backend')
os.chdir(PREVIOUS)

from sqlalchemy import Column, JSON, MetaData, String, Table, Uuid, create_engine, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import sessionmaker
from pgvector.sqlalchemy import Vector
from models.user import User
from models.diary import Diary, DiaryStatus, DiaryOrganized, DiaryEvent, OrganizeTask
from models.graph import (GraphTask, GraphRun, GraphEventPoint, GraphRunEvent,
                          GraphModelCall)
from services.graph_points import validate_points


class StorePointsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.folder = Path(self.tmp.name)
        self.engine = create_engine('sqlite:///:memory:')
        self.addCleanup(self.engine.dispose)
        metadata = MetaData()
        # 模拟现有字段；PostgreSQL 约束由正式迁移定义，本套测试不声称验证它们。
        for model in (User, Diary, DiaryOrganized, DiaryEvent, OrganizeTask, GraphTask, GraphRun,
                      GraphEventPoint, GraphRunEvent, GraphModelCall):
            Table(model.__tablename__, metadata, *(Column(c.name,
                Uuid() if isinstance(c.type, UUID) else JSON() if isinstance(c.type, JSONB)
                else String() if isinstance(c.type, Vector) else c.type,
                primary_key=c.primary_key, nullable=True) for c in model.__table__.columns))
        metadata.create_all(self.engine)
        self.Session = sessionmaker(bind=self.engine, expire_on_commit=False)
        self.db = self.Session()
        self.addCleanup(self.db.close)
        self.config = {'embedding_model': 'isolated-model', 'embedding_max_chars': 8000}
        for name in ('database.SessionLocal', 'services.graph_runtime.SessionLocal'):
            p = patch(name, self.Session)
            p.start(); self.addCleanup(p.stop)
        p = patch('store_points.freeze_embedding_config', side_effect=lambda: deepcopy(self.config))
        p.start(); self.addCleanup(p.stop)
        user = User(id=uuid4(), username='isolated', password_encrypted='placeholder')
        diary = Diary(id=uuid4(), user_id=user.id, diary_date=date(2026, 9, 9), original_text='原文',
                      status=DiaryStatus.organized, is_dirty=False, content_revision=2)
        org = DiaryOrganized(id=uuid4(), diary_id=diary.id, task_id=uuid4(), introduction='',
                            trivia='[]', plans='[]', source_content_revision=2, structured_revision=2)
        self.event = DiaryEvent(id=uuid4(), diary_organized_id=org.id, event_title='相同标题', body='["有效经历。"]',
                               feeling='[]', reflection='[]', ai_importance='HIGH', sort_order=0)
        self.low = DiaryEvent(id=uuid4(), diary_organized_id=org.id, event_title='相同标题', body='["日常经历。"]',
                             feeling='[]', reflection='[]', ai_importance='LOW', sort_order=1)
        self.db.add_all([user, diary, org, self.event, self.low]); self.db.commit()
        self.diary, self.user = diary, user
        self.source = {'schema_version': 1, 'origin': 'database', 'username': user.username,
            'user_id': str(user.id), 'diary_id': str(diary.id), 'diary_date': str(diary.diary_date),
            'organized_id': str(org.id), 'content_revision': 2, 'structured_revision': 2,
            'events': [self.source_event(self.event), self.source_event(self.low)]}
        self.source['source_sha256'] = digest(self.source)
        self.source_path = self.folder / 'source.json'
        self.source_path.write_text(json.dumps(self.source, ensure_ascii=False))
        self.markdown = self.folder / '事件要点.md'
        self.markdown.write_text('# 日记事件要点\n\n来源：来源文件。\n\n' + ''.join(
            f'## 事件：{e["title"]}\n\n<!-- event_id: {e["event_id"]} -->\n\n'
            f'### 1. 要点中心\n\n{e["body"][0]}\n\n' for e in self.source['events']))

    def source_event(self, event):
        return {'event_id': str(event.id), 'title': event.event_title, 'body': json.loads(event.body),
                'feeling': [], 'reflection': [], 'source_order': event.sort_order,
                'effective_importance': event.user_importance or event.ai_importance}

    def packet(self):
        return prepare(self.db, self.markdown, self.source_path)

    def send(self, packet=None):
        packet = packet or self.packet()
        task, reused = submit(self.db, packet, packet['confirmation_sha256'])
        self.db.commit()
        return task, reused

    def test_prepare_preserves_exact_text_and_all_events(self):
        p = self.packet()
        self.assertEqual([e['event_id'] for e in p['events']], [str(self.event.id), str(self.low.id)])
        self.assertEqual([e['points'][0]['detail'] for e in p['events']], ['有效经历。', '日常经历。'])
        self.assertNotIn('excluded_event_ids', p)
        self.assertEqual(p['schema_version'], 3)
        self.assertEqual(self.db.query(GraphTask).count(), 0)
        validate_points({k: p['events'][0][k] for k in ('title', 'points')}, {'title': self.event.event_title})

    def test_parser_rejects_bad_identity_structure_and_number(self):
        original = self.markdown.read_text()
        for changed in (original.replace('### 1.', '### 2.', 1),
                        original.replace(f'<!-- event_id: {self.event.id} -->', ''),
                        original.replace(str(self.low.id), str(self.event.id)),
                        original + '\n## 其他栏目\n内容', original.replace('有效经历。', '')):
            with self.subTest(changed=changed[-40:]), self.assertRaises(StorageError):
                parse_markdown(changed)

    def test_fingerprint_and_legacy_packet_rejected(self):
        p = self.packet()
        with self.assertRaises(StorageError): verify_packet(p, 'wrong')
        altered = deepcopy(p); altered['events'][0]['points'][0]['detail'] = '篡改'
        with self.assertRaises(StorageError): verify_packet(altered)
        old = deepcopy(p); old['schema_version'] = 1
        with self.assertRaises(StorageError): verify_packet(old)
        self.markdown.write_text(self.markdown.read_text() + '\n新增文字')
        with self.assertRaises(StorageError): verify_packet(p)
        verify_packet(p, files=False)

    def test_previous_filtered_packet_can_only_be_used_for_status(self):
        p = self.packet()
        p['schema_version'] = 2
        p['events'] = p['events'][:1]
        p['excluded_event_ids'] = [str(self.low.id)]
        p['confirmation_sha256'] = digest({k: v for k, v in p.items() if k != 'confirmation_sha256'})
        verify_packet(p, files=False)
        with self.assertRaisesRegex(StorageError, '旧入库包'):
            verify_packet(p)

    def test_rehashed_packet_cannot_change_text_or_target(self):
        for field in ('text', 'user'):
            p = self.packet()
            if field == 'text': p['events'][0]['points'][0]['detail'] = '伪造'
            else: p['user_id'] = str(uuid4())
            p['confirmation_sha256'] = digest({k: v for k, v in p.items() if k != 'confirmation_sha256'})
            with self.assertRaises(StorageError): verify_packet(p)

    def test_changed_content_or_revision_stops(self):
        p = self.packet()
        for field, changed in [('body', '["已改正文。"]')]:
            old = getattr(self.event, field)
            setattr(self.event, field, changed); self.db.flush()
            with self.assertRaises(StorageError): submit(self.db, p, p['confirmation_sha256'])
            setattr(self.event, field, old); self.db.flush()
        self.diary.content_revision = 3; self.db.flush()
        with self.assertRaises(StorageError): submit(self.db, p, p['confirmation_sha256'])

    def test_new_event_prevents_partial_store(self):
        p = self.packet()
        self.db.add(DiaryEvent(id=uuid4(), diary_organized_id=self.event.diary_organized_id,
            event_title='新增事件', body='["新增经历。"]', feeling='[]', reflection='[]',
            ai_importance='LOW', sort_order=2))
        self.db.flush()
        with self.assertRaises(StorageError): submit(self.db, p, p['confirmation_sha256'])

    def test_importance_change_does_not_invalidate_confirmed_packet(self):
        p = self.packet()
        self.event.user_importance = 'LOW'
        self.low.ai_importance = None
        self.db.flush()
        self.assertEqual(self.packet()['points_source_sha256'], p['points_source_sha256'])
        task, _ = self.send(p)
        run = self.db.query(GraphRun).filter(GraphRun.task_id == task.id).one()
        self.assertEqual(len(run.checkpoint['point_work']), 2)

    def test_source_without_importance_metadata_can_be_stored(self):
        for event in self.source['events']:
            event.pop('effective_importance')
        self.source['source_sha256'] = digest({k: v for k, v in self.source.items() if k != 'source_sha256'})
        self.source_path.write_text(json.dumps(self.source, ensure_ascii=False))
        task, _ = self.send()
        run = self.db.query(GraphRun).filter(GraphRun.task_id == task.id).one()
        self.assertEqual(len(run.checkpoint['point_work']), 2)

    def test_all_low_events_are_included_and_partial_source_is_rejected(self):
        self.event.user_importance = 'LOW'; self.db.flush()
        self.assertEqual(len(self.packet()['events']), 2)
        partial = {**self.source, 'events': self.source['events'][:1]}
        with self.assertRaisesRegex(StorageError, '全部事件'):
            target(self.db, partial)

    def test_wrong_user_config_and_missing_confirmation_stop(self):
        wrong = deepcopy(self.source); wrong['user_id'] = str(uuid4())
        with self.assertRaises(StorageError): target(self.db, wrong)
        p = self.packet()
        with self.assertRaises(StorageError): submit(self.db, p, None)
        self.config['embedding_model'] = 'changed'
        with self.assertRaisesRegex(StorageError, '配置已变化'): submit(self.db, p, p['confirmation_sha256'])

    def test_submit_cannot_be_claimed_by_default_worker(self):
        from services.task_environment import TASK_ENVIRONMENT
        task, _ = self.send()
        self.assertNotEqual(task.environment, TASK_ENVIRONMENT)
        self.assertEqual(task.config_snapshot['scope'], 'EVENT_POINTS')
        self.assertEqual(set(task.config_snapshot) - {'scope', 'skill_import'}, set(self.config))

    def test_same_packet_reuses_task_point_ids_and_atomic_create(self):
        p = self.packet(); task, reused = self.send(p)
        self.assertFalse(reused)
        run = self.db.query(GraphRun).filter(GraphRun.task_id == task.id).one()
        before = deepcopy(run.checkpoint)
        again, reused = self.send(p)
        self.assertTrue(reused); self.assertEqual(again.id, task.id)
        self.assertEqual(run.checkpoint, before)
        self.assertEqual(self.db.query(GraphTask).count(), 1)

    def test_rollback_leaves_no_half_created_task(self):
        p = self.packet()
        submit(self.db, p, p['confirmation_sha256']); self.db.rollback()
        self.assertEqual(self.db.query(GraphTask).count(), 0)
        self.assertEqual(self.db.query(GraphRun).count(), 0)

    def test_readonly_blocks_mutations(self):
        self.db.rollback(); readonly(self.db)
        with self.assertRaises(Exception): self.db.execute(text('DELETE FROM graph_tasks'))
        self.db.rollback(); self.db.execute(text('PRAGMA query_only = OFF'))

    def response(self, *args, **kwargs):
        self.assertEqual(args[0], 'embedding')
        self.assertTrue(kwargs.get('embedding'))
        return {'data': [{'index': 0, 'embedding': [1.0] + [0.0]*1023}]}

    def test_only_embedding_is_called_and_points_ready_leaves_diary_untouched(self):
        p = self.packet(); task, _ = self.send(p)
        raw = self.markdown.read_bytes()
        with patch('services.graph_runtime.GraphContext.call', AsyncMock(side_effect=self.response)) as call:
            asyncio.run(execute(self.Session, task.id, p))
        self.db.expire_all()
        result = status(self.db, self.db.get(GraphTask, task.id))
        self.assertTrue(result['stored']); self.assertEqual(result['stored_points'], 2)
        self.assertEqual(result['vectors'], 2)
        self.assertEqual(call.await_count, 2)
        points = self.db.query(GraphEventPoint).all()
        self.assertEqual({point.detail for point in points}, {'有效经历。', '日常经历。'})
        run = self.db.query(GraphRun).one()
        self.assertEqual(run.status, 'POINTS_READY'); self.assertIsNone(run.published_at)
        self.assertEqual(self.db.get(Diary, self.diary.id).status, DiaryStatus.organized)
        self.assertFalse(self.db.get(DiaryEvent, self.event.id).is_in_graph)
        self.assertFalse(self.db.get(DiaryEvent, self.low.id).is_in_graph)
        self.assertEqual(self.markdown.read_bytes(), raw)
        # 已完成包再次执行，不重复向量调用或写入。
        again, reused = self.send(p)
        self.assertTrue(reused)
        with patch('services.graph_runtime.GraphContext.call', AsyncMock(side_effect=AssertionError('重复请求'))):
            asyncio.run(execute(self.Session, again.id, p))
        self.assertEqual(self.db.query(GraphEventPoint).count(), 2)

    def test_invalid_vector_rolls_back_and_failed_task_can_resume(self):
        p = self.packet(); task, _ = self.send(p)
        with patch('services.graph_runtime.GraphContext.call', AsyncMock(return_value={'data': [{'index': 0, 'embedding': [0.0]}]})):
            with self.assertRaises(StorageError): asyncio.run(execute(self.Session, task.id, p))
        self.db.expire_all()
        self.assertEqual(self.db.get(GraphTask, task.id).status, 'FAILED')
        self.assertEqual(self.db.query(GraphEventPoint).count(), 0)
        self.assertEqual(self.db.query(GraphRunEvent).count(), 0)
        with patch('services.graph_runtime.GraphContext.call', AsyncMock(side_effect=self.response)):
            asyncio.run(execute(self.Session, task.id, p))
        self.db.expire_all()
        self.assertTrue(status(self.db, self.db.get(GraphTask, task.id))['stored'])
        self.assertEqual(self.db.query(GraphTask).count(), 1)

    def test_changed_source_before_final_commit_saves_no_points(self):
        p = self.packet(); task, _ = self.send(p)
        async def response(*args, **kwargs):
            with self.Session() as db:
                row = db.get(DiaryEvent, self.event.id)
                row.body = '["期间变化。"]'; db.commit()
            return self.response(*args, **kwargs)
        with patch('services.graph_runtime.GraphContext.call', AsyncMock(side_effect=response)):
            with self.assertRaises(StorageError): asyncio.run(execute(self.Session, task.id, p))
        self.db.expire_all()
        self.assertEqual(self.db.query(GraphEventPoint).count(), 0)
        self.assertEqual(self.db.query(GraphRunEvent).count(), 0)

    def test_reuses_exact_detail_vectors_from_prior_attempt(self):
        prior = GraphTask(id=uuid4(), user_id=self.user.id, entry_type='HISTORY', status='SUPERSEDED',
            date_from=self.diary.diary_date, date_to=self.diary.diary_date,
            config_snapshot={'embedding_model': self.config['embedding_model']})
        self.db.add(prior); self.db.flush()
        pid = str(uuid4())
        run = GraphRun(id=uuid4(), task_id=prior.id, user_id=self.user.id, diary_id=self.diary.id,
            diary_date=self.diary.diary_date, status='FAILED', checkpoint={'point_work': {
                str(self.event.id): {'points': [{'id': pid, 'detail': '有效经历。'}]}},
                'vectors': {pid: [1.0] + [0.0]*1023}})
        self.db.add(run); self.db.commit()
        p = self.packet(); task, _ = self.send(p)
        with patch('services.graph_runtime.GraphContext.call', AsyncMock(side_effect=self.response)) as call:
            asyncio.run(execute(self.Session, task.id, p))
        self.db.expire_all()
        result = status(self.db, self.db.get(GraphTask, task.id))
        self.assertTrue(result['stored']); self.assertEqual(result['reused_vectors'], 1)
        self.assertEqual(result['stored_points'], 2)
        self.assertEqual(call.await_count, 1)
        with self.assertRaisesRegex(StorageError, '已有有效要点'): self.packet()


if __name__ == '__main__':
    unittest.main()
