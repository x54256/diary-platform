"""显式指向一次性本机容器的真实 PostgreSQL 发布验证。"""
from copy import deepcopy
from datetime import date
import os
import json
from pathlib import Path
import sys
import unittest
from uuid import UUID, uuid4

from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

import storage as s
import workflow as w
import test_storage

URL=os.environ.get('RELATIONS_TEST_DATABASE_URL')


@unittest.skipUnless(URL,'需显式指定一次性本机 PostgreSQL 容器')
class PostgresStorageTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        url=make_url(URL)
        if url.host!='127.0.0.1' or url.port!=55449 or url.database!='graph_test':
            raise RuntimeError('拒绝非指定隔离数据库')
        sys.path.insert(0,str(w.PROJECT_ROOT/'backend'))
        from database import Base
        import models
        cls.engine=create_engine(url)
        with cls.engine.begin()as c:c.exec_driver_sql('CREATE EXTENSION IF NOT EXISTS vector')
        Base.metadata.create_all(cls.engine)

    @classmethod
    def tearDownClass(cls):cls.engine.dispose()

    def setUp(self):
        self.fixture=test_storage.StorageTest();self.fixture.setUp();self.addCleanup(self.fixture.doCleanups)
        self.packet=self.fixture.packet;f=self.fixture.fixture
        from models.user import User
        from models.diary import Diary, DiaryEvent, DiaryOrganized, OrganizeTask, DiaryStatus
        from models.graph import GraphTask, GraphRun, GraphRunEvent, GraphEventPoint
        with Session(self.engine)as db:
            uid,did,oid,rid=map(UUID,(f.uid,f.did,f.oid,f.rid));day=date(2026,9,9)
            db.add(User(id=uid,username='isolated-'+f.uid,password_encrypted='isolated'));db.flush()
            db.add(Diary(id=did,user_id=uid,diary_date=day,original_text='原文',status=DiaryStatus.organized));db.flush()
            orgtask=OrganizeTask(id=uuid4(),diary_id=did,user_id=uid,status='completed',task_type='organize');db.add(orgtask);db.flush()
            db.add(DiaryOrganized(id=oid,diary_id=did,task_id=orgtask.id,title='隔离',introduction='',trivia='[]',plans='[]'));db.flush()
            task=GraphTask(id=uuid4(),user_id=uid,entry_type='HISTORY',status='SUCCEEDED',date_from=day,date_to=day,config_snapshot={});db.add(task);db.flush()
            events=list(self.packet['snapshot']['events'].values())
            source={**f.source,'events':[{**f.source['events'][0],'event_id':e['id'],'source_order':e['source_order']}for e in events]}
            db.add(GraphRun(id=rid,task_id=task.id,user_id=uid,diary_id=did,diary_date=day,source_organized_id=oid,status='POINTS_READY',source_snapshot=source,source_sha256=w.digest(source),checkpoint={'points_stage':'preserved'}));db.flush()
            for e in events:
                db.add(DiaryEvent(id=UUID(e['id']),diary_organized_id=oid,event_title='同名事件',body=json.dumps(['具体经历。']),feeling='[]',reflection='[]',sort_order=e['source_order'],ai_importance='MEDIUM'));db.flush()
                db.add(GraphRunEvent(run_id=rid,event_id=UUID(e['id']),user_id=uid,source_order=e['source_order']));db.flush()
                for p in e['points']:
                    db.add(GraphEventPoint(id=UUID(p['id']),run_id=rid,event_id=UUID(e['id']),user_id=uid,no=p['no'],summary=p['summary'],detail=p['detail'],embedding=[1.]+[0.]*1023,embedding_model='same-model'))
            db.commit()
        # 来源快照与数据库保持一致，用户名在本地包外不借用真实配置。
        with s.readonly(self.engine)as c:events,vs=s.load_run(c,f.uid,f.rid)
        folder=w.write_package(w.prepare_data(events,[],vs,w.settings()),self.fixture.root/'postgres')
        snapshot,_=w.load_package(folder)
        old={r['pair_id']:r for r in self.packet['results']}
        w.write_json(folder/'input.json',{'package_sha256':snapshot['package_sha256'],'results':list(old.values())})
        w.record(folder,folder/'input.json')
        w.render(folder)
        self.packet=s.build_packet(folder,'isolated-'+f.uid)

    def publish(self):
        with self.engine.begin()as c:return s.publish(c,self.packet,self.packet['username'],self.packet['storage_sha256'])

    def test_real_constraints_checkpoint_and_idempotence(self):
        self.assertTrue(self.publish()['stored']);self.assertTrue(self.publish()['stored'])
        with self.engine.connect()as c:
            cp=c.execute(text('SELECT checkpoint FROM graph_runs WHERE id=:id'),{'id':self.packet['current_run_id']}).scalar()
            self.assertEqual(3,len(cp['skill_relations']['results']))
            self.assertEqual(1,c.execute(text('SELECT count(*) FROM graph_event_relations WHERE run_id=:id'),{'id':self.packet['current_run_id']}).scalar())

    def test_fixed_migration_from_legacy_is_idempotent(self):
        with self.engine.begin()as c:
            c.exec_driver_sql('ALTER TABLE graph_event_relations DROP CONSTRAINT ck_graph_relation_description')
            c.exec_driver_sql("ALTER TABLE graph_event_relations ADD CONSTRAINT ck_graph_relation_description CHECK(btrim(description)<>'' AND final_source IN ('AGREEMENT','ADJUDICATED')) NOT VALID")
            self.assertFalse(s.schema(c)['skill_source_supported'])
            self.assertTrue(s.schema(c,write=True)['changed'])
            self.assertFalse(s.schema(c,write=True)['changed'])
        self.assertTrue(self.publish()['stored'])

    def test_user_lock_serializes_publish(self):
        with self.engine.begin()as first:
            first.execute(text('SELECT id FROM users WHERE id=:id FOR UPDATE'),{'id':self.packet['user_id']})
            with self.assertRaises(Exception):
                with self.engine.begin()as second:
                    second.exec_driver_sql("SET LOCAL lock_timeout='200ms'")
                    s.publish(second,self.packet,self.packet['username'],self.packet['storage_sha256'])
        self.assertTrue(self.publish()['stored'])

    def test_real_evidence_failure_rolls_back(self):
        with self.engine.begin()as c:
            c.exec_driver_sql("ALTER TABLE graph_relation_evidence ADD CONSTRAINT isolated_evidence_fail CHECK (side <> 'TARGET') NOT VALID")
        try:
            with self.assertRaises(Exception):self.publish()
            with self.engine.connect()as c:
                self.assertEqual('POINTS_READY',c.execute(text('SELECT status FROM graph_runs WHERE id=:id'),{'id':self.packet['current_run_id']}).scalar())
                self.assertEqual(0,c.execute(text('SELECT count(*) FROM graph_event_relations WHERE run_id=:id'),{'id':self.packet['current_run_id']}).scalar())
        finally:
            with self.engine.begin()as c:c.exec_driver_sql('ALTER TABLE graph_relation_evidence DROP CONSTRAINT isolated_evidence_fail')


if __name__=='__main__':unittest.main()
