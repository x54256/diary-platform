"""内存 SQLite 验证读取逻辑；PostgreSQL 专属约束由原有数据库测试覆盖。"""
import unittest
from datetime import date, datetime
from types import SimpleNamespace
from uuid import uuid4
from fastapi import HTTPException
from sqlalchemy import Column, JSON, MetaData, String, Table, Uuid, create_engine
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Session
from pgvector.sqlalchemy import Vector
import models
from models.diary import Diary, DiaryEvent
from models.graph import GraphRun, GraphRunEvent, GraphEventPoint, GraphEventRelation, GraphRelationEvidence
from routers.graph import current_graph, event_neighbors


class GraphBrowseTest(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine('sqlite:///:memory:')
        metadata = MetaData()
        for model in (Diary, DiaryEvent, GraphRun, GraphRunEvent, GraphEventPoint, GraphEventRelation, GraphRelationEvidence):
            Table(model.__tablename__, metadata, *(Column(column.name,
                Uuid() if isinstance(column.type, UUID) else JSON() if isinstance(column.type, JSONB) else String() if isinstance(column.type, Vector) else column.type,
                primary_key=column.primary_key, nullable=True) for column in model.__table__.columns))
        metadata.create_all(self.engine)
        self.db = Session(self.engine)
        self.addCleanup(self.engine.dispose)
        self.addCleanup(self.db.close)
        self.user = SimpleNamespace(id=uuid4())

    def node(self, day, title='事件', run=None):
        if run is None:
            diary = Diary(id=uuid4(), user_id=self.user.id, diary_date=date(2026, 10, day), original_text='测试')
            run = GraphRun(id=uuid4(), task_id=uuid4(), diary_id=diary.id, user_id=self.user.id,
                diary_date=diary.diary_date, status='PUBLISHED', published_at=datetime.now(), source_snapshot={'events': []})
            self.db.add_all([diary, run])
        event = DiaryEvent(id=uuid4(), diary_organized_id=uuid4(), event_title=title, is_in_graph=True, sort_order=0)
        run.source_snapshot = {'events': run.source_snapshot['events'] + [{'event_id': str(event.id), 'title': title}]}
        point = GraphEventPoint(id=uuid4(), run_id=run.id, event_id=event.id, user_id=self.user.id,
            no=1, summary=title, detail=f'{title}的详细依据', embedding_model='test')
        self.db.add_all([event, GraphRunEvent(run_id=run.id, event_id=event.id, user_id=self.user.id, source_order=0), point])
        self.db.flush()
        return run, event, point

    def edge(self, source, target):
        sr, se, sp = source; tr, te, tp = target
        edge = GraphEventRelation(id=uuid4(), run_id=tr.id, user_id=self.user.id,
            source_run_id=sr.id, source_event_id=se.id, target_run_id=tr.id, target_event_id=te.id,
            relation_type='后续事件', certainty='EXPLICIT', description='继续推进', final_source='AGREEMENT')
        self.db.add(edge)
        for side, run, event, point in [('SOURCE', sr, se, sp), ('TARGET', tr, te, tp)]:
            self.db.add(GraphRelationEvidence(relation_id=edge.id, side=side, point_id=point.id,
                user_id=self.user.id, source_run_id=sr.id, source_event_id=se.id,
                target_run_id=tr.id, target_event_id=te.id, point_run_id=run.id, point_event_id=event.id))
        self.db.flush()
        return edge

    def test_cross_diary_endpoints_and_evidence_are_complete_from_both_sides(self):
        a, b = self.node(1, '预约'), self.node(2, '就诊')
        self.edge(a, b)
        for root in (a, b):
            result = current_graph(root[0].diary_id, self.db, self.user)
            nodes = {item['event_id']: item for item in result['events']}
            self.assertEqual(set(nodes), {a[1].id, b[1].id})
            self.assertEqual(nodes[a[1].id]['diary_id'], a[0].diary_id)
            self.assertEqual(nodes[b[1].id]['title'], '就诊')
            self.assertEqual(nodes[b[1].id]['points'][0]['detail'], '就诊的详细依据')
            self.assertEqual(result['relations'][0]['target_points'][0]['point_id'], b[2].id)

    def test_neighbors_exclude_sibling_events_and_their_relations(self):
        a = self.node(1); sibling = self.node(1, run=a[0])
        b, c = self.node(2), self.node(3)
        wanted = self.edge(a, b); self.edge(sibling, c)
        result = event_neighbors(a[1].id, self.db, self.user)
        self.assertEqual({item['event_id'] for item in result['events']}, {a[1].id, b[1].id})
        self.assertEqual([item['id'] for item in result['relations']], [wanted.id])

    def test_deleted_or_obsolete_neighbor_is_filtered(self):
        a, b = self.node(1), self.node(2)
        self.edge(a, b)
        for mode in ('deleted', 'obsolete', 'not_in_graph'):
            self.db.get(Diary, b[0].diary_id).deleted_at = datetime.now() if mode == 'deleted' else None
            b[0].status = 'OBSOLETE' if mode == 'obsolete' else 'PUBLISHED'
            b[1].is_in_graph = mode != 'not_in_graph'
            self.db.flush()
            result = current_graph(a[0].diary_id, self.db, self.user)
            self.assertEqual([item['event_id'] for item in result['events']], [a[1].id])
            self.assertEqual(result['relations'], [])

    def test_foreign_user_and_unpublished_event_are_not_readable(self):
        a = self.node(1)
        with self.assertRaises(HTTPException) as denied:
            event_neighbors(a[1].id, self.db, SimpleNamespace(id=uuid4()))
        self.assertEqual(denied.exception.status_code, 404)
        a[0].status = 'OBSOLETE'; self.db.flush()
        with self.assertRaises(HTTPException): event_neighbors(a[1].id, self.db, self.user)
        self.assertEqual(current_graph(a[0].diary_id, self.db, self.user)['events'], [])

    def test_points_ready_is_visible_without_changing_graph_flags(self):
        ready = self.node(9, '已保存的要点')
        ready[0].status = 'POINTS_READY'
        ready[0].published_at = None
        ready[1].is_in_graph = False
        self.db.flush()
        for result in (current_graph(ready[0].diary_id, self.db, self.user),
                       event_neighbors(ready[1].id, self.db, self.user)):
            self.assertEqual(result['run']['status'], 'POINTS_READY')
            self.assertEqual([e['event_id'] for e in result['events']], [ready[1].id])
            self.assertEqual(result['events'][0]['points'][0]['detail'], '已保存的要点的详细依据')
            self.assertEqual(result['relations'], [])
        self.assertFalse(ready[1].is_in_graph)
        self.assertIsNone(ready[0].published_at)

    def test_points_ready_does_not_expose_unpublished_connections_or_foreign_data(self):
        ready, published = self.node(9), self.node(10)
        self.edge(ready, published)
        ready[0].status = 'POINTS_READY'; ready[1].is_in_graph = False
        self.db.flush()
        result = current_graph(ready[0].diary_id, self.db, self.user)
        self.assertEqual([e['event_id'] for e in result['events']], [ready[1].id])
        self.assertEqual(result['relations'], [])
        with self.assertRaises(HTTPException):
            current_graph(ready[0].diary_id, self.db, SimpleNamespace(id=uuid4()))
        with self.assertRaises(HTTPException):
            event_neighbors(ready[1].id, self.db, SimpleNamespace(id=uuid4()))

    def test_newer_failed_attempt_does_not_hide_ready_points(self):
        ready = self.node(9, '可读要点')
        ready[0].status = 'POINTS_READY'; ready[1].is_in_graph = False
        failed = GraphRun(id=uuid4(), task_id=uuid4(), diary_id=ready[0].diary_id,
            user_id=self.user.id, diary_date=ready[0].diary_date, status='FAILED', source_snapshot={'events': []})
        self.db.add(failed); self.db.flush()
        result = current_graph(ready[0].diary_id, self.db, self.user)
        self.assertIsNotNone(result['run'])
        self.assertEqual(result['run']['id'], ready[0].id)
