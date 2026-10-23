"""仅显式指向一次性本机补充测试容器；真实向量与复合外键事务。"""
import os
import unittest
from unittest.mock import patch

from sqlalchemy import create_engine,text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

import test_supplement_points
import supplement_points as s
from database import Base
import models
from models.user import User
from models.diary import Diary,DiaryEvent,DiaryOrganized,OrganizeTask
from models.graph import GraphTask,GraphRun,GraphRunEvent,GraphEventPoint

URL=os.environ.get('POINTS_SUPPLEMENT_TEST_DATABASE_URL')


@unittest.skipUnless(URL,'需显式一次性本机 PostgreSQL 补充测试容器')
class SupplementPostgresTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        url=make_url(URL)
        if url.host!='127.0.0.1'or url.port!=55459 or url.database!='points_supplement_test':raise RuntimeError('拒绝非隔离数据库')
        cls.engine=create_engine(url)
        with cls.engine.begin()as c:c.exec_driver_sql('CREATE EXTENSION IF NOT EXISTS vector')
        Base.metadata.create_all(cls.engine);cls.Session=sessionmaker(bind=cls.engine,expire_on_commit=False)
    @classmethod
    def tearDownClass(cls):cls.engine.dispose()
    def setUp(self):
        self.fixture=test_supplement_points.SupplementTest();self.fixture.setUp();self.addCleanup(self.fixture.doCleanups)
        with self.engine.begin()as c:c.exec_driver_sql('TRUNCATE users CASCADE')
        with self.fixture.Session()as old,self.Session()as new:
            # 完整实际 ORM 字段定义生效，补齐 SQLite 模拟来源的整理任务父记录。
            for model in (User,Diary):
                for row in old.query(model):new.execute(model.__table__.insert().values(**{c.name:getattr(row,c.name)for c in model.__table__.columns}))
            org=old.query(DiaryOrganized).one()
            new.add(OrganizeTask(id=org.task_id,diary_id=org.diary_id,user_id=self.fixture.f.user.id,status='completed',task_type='organize'));new.flush()
            for model in (DiaryOrganized,DiaryEvent,GraphTask,GraphRun,GraphRunEvent,GraphEventPoint):
                for row in old.query(model):new.execute(model.__table__.insert().values(**{c.name:getattr(row,c.name)for c in model.__table__.columns}))
            new.commit()
        with self.Session()as db:self.packet=s.prepare(db,self.fixture.inputs)
    def test_append_and_repeat_under_actual_constraints(self):
        result=s.publish(self.Session,self.packet,self.fixture.vectors,self.packet['confirmation_sha256'])
        self.assertTrue(result['stored']);self.assertTrue(result['items'][0]['existing_content_unchanged'])
        self.assertTrue(s.publish(self.Session,self.packet,self.fixture.vectors,self.packet['confirmation_sha256'])['stored'])
    def test_evidence_failure_rolls_back_missing_event_node(self):
        with self.engine.begin()as c:
            c.exec_driver_sql("ALTER TABLE graph_event_points ADD CONSTRAINT isolated_fail CHECK (detail <> '日常经历。') NOT VALID")
        try:
            with self.assertRaises(Exception):s.publish(self.Session,self.packet,self.fixture.vectors,self.packet['confirmation_sha256'])
            with self.Session()as db:self.assertEqual(1,db.query(GraphRunEvent).count())
        finally:
            with self.engine.begin()as c:c.exec_driver_sql('ALTER TABLE graph_event_points DROP CONSTRAINT isolated_fail')
    def test_existing_published_run_preserved(self):
        from models.graph import utcnow
        with self.Session()as db:
            run=db.query(GraphRun).one();run.status='PUBLISHED';run.published_at=utcnow()
            db.query(DiaryEvent).update({'is_in_graph':True});db.commit()
        with self.Session()as db:self.packet=s.prepare(db,self.fixture.inputs)
        result=s.publish(self.Session,self.packet,self.fixture.vectors,self.packet['confirmation_sha256'])
        self.assertTrue(result['stored']);self.assertEqual('PUBLISHED',result['items'][0]['run_status'])


if __name__=='__main__':unittest.main()
