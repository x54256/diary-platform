"""追加路径隔离验证，不访问实际数据库或模型服务。"""
from copy import deepcopy
import json
import unittest
from unittest.mock import patch
from uuid import uuid4

import test_store_points as base
import supplement_points as s
from store_points import digest, StorageError
from models.graph import GraphTask,GraphRun,GraphRunEvent,GraphEventPoint
from sqlalchemy import text


class SupplementTest(unittest.TestCase):
    def setUp(self):
        self.f=base.StorePointsTest();self.f.setUp();self.addCleanup(self.f.doCleanups)
        self.Session=self.f.Session;self.config={'embedding_model':'isolated-model','embedding_max_chars':8000,'models':{'embedding':{'model_name':'isolated'}}}
        p=patch('supplement_points.freeze_embedding_config',return_value=self.config);p.start();self.addCleanup(p.stop)
        with self.Session()as db:
            task=GraphTask(id=uuid4(),user_id=self.f.user.id,entry_type='HISTORY',status='SUCCEEDED',date_from=self.f.diary.diary_date,date_to=self.f.diary.diary_date,config_snapshot=self.config)
            db.add(task);db.flush()
            source={k:self.f.source[k]for k in ('user_id','diary_id','diary_date','organized_id','content_revision','structured_revision','events')};source['scope']='EVENT_POINTS'
            run=GraphRun(id=uuid4(),task_id=task.id,user_id=task.user_id,diary_id=self.f.diary.id,diary_date=self.f.diary.diary_date,
                source_organized_id=self.f.diary.organized.id,status='POINTS_READY',source_snapshot=source,source_sha256=digest(source),
                checkpoint={'original':'preserved','skill_relations':{'storage_sha256':'original-version'}})
            db.add(run);db.flush();self.rid=str(run.id)
            db.add(GraphRunEvent(run_id=run.id,event_id=self.f.event.id,user_id=run.user_id,source_order=0));db.flush()
            db.add(GraphEventPoint(id=uuid4(),run_id=run.id,event_id=self.f.event.id,user_id=run.user_id,no=1,summary='要点中心',detail='有效经历。',embedding=[1.]+[0.]*1023,embedding_model='isolated-model'))
            db.commit()
        self.inputs=[{'source':str(self.f.source_path),'markdown':str(self.f.markdown),'run_id':self.rid}]
        with self.Session()as db:self.packet=s.prepare(db,self.inputs)
        self.vectors={p['id']:[1.]+[0.]*1023 for item in self.packet['items']for e in item['events']for p in e['points']}

    def test_only_low_added_preserving_original_and_idempotent(self):
        self.assertEqual(1,len(self.packet['items'][0]['events']))
        self.assertFalse(s.status(self.Session,self.packet)['stored'])
        result=s.publish(self.Session,self.packet,self.vectors,self.packet['confirmation_sha256'])
        self.assertTrue(result['stored']);self.assertTrue(result['items'][0]['existing_content_unchanged'])
        self.assertTrue(s.publish(self.Session,self.packet,self.vectors,self.packet['confirmation_sha256'])['stored'])
        with self.Session()as db:
            self.assertEqual(2,db.query(GraphEventPoint).count());self.assertEqual(2,db.query(GraphRunEvent).count())
            run=db.query(GraphRun).one()
            self.assertEqual('POINTS_READY',run.status);self.assertEqual('SUCCEEDED',db.query(GraphTask).one().status)
            self.assertEqual({'storage_sha256':'original-version'},run.checkpoint['skill_relations'])

    def test_all_missing_events_and_metadata_changes_use_same_packet(self):
        from models.diary import DiaryEvent
        # 数据库旧字段的任何取值都不影响补充范围或新来源内容。
        for value in ('HIGH','MEDIUM',None):
            with self.subTest(value=value):
                with self.Session()as db:
                    db.get(DiaryEvent,self.f.low.id).ai_importance=value;db.commit()
                with self.Session()as db:packet=s.prepare(db,self.inputs)
                self.assertEqual(self.packet,packet)
                self.assertNotIn('importance',json.dumps(packet,ensure_ascii=False))
        self.assertEqual(2,self.packet['schema_version'])
        self.assertEqual('diary-event-points-supplement',self.packet['kind'])

    def test_published_run_stays_published_new_node_flag_and_original_audit_preserved(self):
        with self.Session()as db:
            run=db.query(GraphRun).one();run.status='PUBLISHED';self.f.event.is_in_graph=True;db.commit()
        with self.Session()as db:self.packet=s.prepare(db,self.inputs)
        result=s.publish(self.Session,self.packet,self.vectors,self.packet['confirmation_sha256'])
        self.assertTrue(result['stored']);self.assertEqual('PUBLISHED',result['items'][0]['run_status'])
        with self.Session()as db:
            from models.diary import DiaryEvent
            self.assertTrue(db.get(DiaryEvent,self.f.low.id).is_in_graph)
            self.assertEqual({'storage_sha256':'original-version'},db.query(GraphRun).one().checkpoint['skill_relations'])

    def test_failure_during_append_rolls_back_all_nodes_and_points(self):
        with self.f.engine.begin()as c:
            c.exec_driver_sql("CREATE TRIGGER fail_low BEFORE INSERT ON graph_event_points BEGIN SELECT RAISE(ABORT,'isolated'); END")
        with self.assertRaises(Exception):s.publish(self.Session,self.packet,self.vectors,self.packet['confirmation_sha256'])
        with self.Session()as db:
            self.assertEqual(1,db.query(GraphRunEvent).count());self.assertEqual(1,db.query(GraphEventPoint).count())
            self.assertNotIn('point_supplements',db.query(GraphRun).one().checkpoint)

    def test_wrong_confirmation_stale_source_and_changed_existing_point_refused(self):
        with self.assertRaises(StorageError):s.publish(self.Session,self.packet,self.vectors,'wrong')
        with self.Session()as db:
            p=db.query(GraphEventPoint).one();p.detail='已被修改';db.commit()
        with self.assertRaises(StorageError):s.publish(self.Session,self.packet,self.vectors,self.packet['confirmation_sha256'])
        self.assertFalse(s.status(self.Session,self.packet)['items'][0]['existing_content_unchanged'])

    def test_draft_change_and_model_change_refused(self):
        self.f.markdown.write_text(self.f.markdown.read_text()+'\n稿后新内容。')
        with self.assertRaises(StorageError):s.verify(self.packet)
        with self.Session()as db:
            p=db.query(GraphEventPoint).one();p.embedding_model='other';db.commit()
        with self.assertRaises(StorageError):
            with self.Session()as db:s.prepare(db,self.inputs)


if __name__=='__main__':unittest.main()
