from contextlib import contextmanager
from copy import deepcopy
import json
from pathlib import Path
from types import SimpleNamespace
import unittest
import tempfile
from unittest.mock import patch
from uuid import uuid4

from sqlalchemy import create_engine, text

import db_source as d
import workflow as w


class DatabaseSourceTest(unittest.TestCase):
    def setUp(self):
        self.engine=create_engine('sqlite:///:memory:');self.addCleanup(self.engine.dispose)
        self.uid,self.did,self.oid,self.eid,self.rid,self.pid=[str(uuid4())for _ in range(6)]
        self.source={'scope':'EVENT_POINTS','user_id':self.uid,'diary_id':self.did,'diary_date':'2026-09-09',
                     'organized_id':self.oid,'content_revision':1,'structured_revision':1,'events':[
                         {'event_id':self.eid,'title':'同名事件','body':['具体经历。'],'feeling':[],
                          'reflection':[],'source_order':0,'importance':'MEDIUM'}]}
        with self.engine.begin()as c:
            for sql in [
                'CREATE TABLE users(id TEXT,username TEXT)',
                'CREATE TABLE diaries(id TEXT,user_id TEXT,diary_date TEXT,status TEXT,is_dirty INTEGER,content_revision INTEGER,original_text TEXT,deleted_at TEXT)',
                'CREATE TABLE diary_organized(id TEXT,diary_id TEXT,source_content_revision INTEGER,structured_revision INTEGER,introduction TEXT,trivia TEXT,plans TEXT)',
                'CREATE TABLE diary_events(id TEXT,diary_organized_id TEXT,event_title TEXT,body TEXT,feeling TEXT,reflection TEXT,sort_order INTEGER,user_importance TEXT,ai_importance TEXT,is_in_graph INTEGER)',
                'CREATE TABLE graph_runs(id TEXT,diary_id TEXT,user_id TEXT,diary_date TEXT,status TEXT,source_organized_id TEXT,source_snapshot TEXT,source_sha256 TEXT,created_at TEXT)',
                'CREATE TABLE graph_run_events(run_id TEXT,event_id TEXT,user_id TEXT,source_order INTEGER,occurred_on TEXT)',
                'CREATE TABLE graph_event_points(id TEXT,run_id TEXT,event_id TEXT,user_id TEXT,no INTEGER,summary TEXT,detail TEXT,embedding TEXT,embedding_model TEXT)']:
                c.exec_driver_sql(sql)
            c.execute(text('INSERT INTO users VALUES(:id,:name)'),{'id':self.uid,'name':'isolated'})
            c.execute(text("INSERT INTO diaries VALUES(:id,:uid,'2026-09-09','organized',0,1,'原文',NULL)"),{'id':self.did,'uid':self.uid})
            c.execute(text("INSERT INTO diary_organized VALUES(:id,:did,1,1,'','[]','[]')"),{'id':self.oid,'did':self.did})
            c.execute(text("INSERT INTO diary_events VALUES(:id,:oid,'同名事件',:body,'[]','[]',0,NULL,'MEDIUM',0)"),
                      {'id':self.eid,'oid':self.oid,'body':json.dumps(['具体经历。'])})
            c.execute(text("INSERT INTO graph_runs VALUES(:rid,:did,:uid,'2026-09-09','POINTS_READY',:oid,:source,:sha,'2026-10-22')"),
                      {'rid':self.rid,'did':self.did,'uid':self.uid,'oid':self.oid,'source':json.dumps(self.source),'sha':w.digest(self.source)})
            c.execute(text('INSERT INTO graph_run_events VALUES(:rid,:eid,:uid,0,NULL)'),{'rid':self.rid,'eid':self.eid,'uid':self.uid})
            c.execute(text("INSERT INTO graph_event_points VALUES(:pid,:rid,:eid,:uid,1,'要点','具体经历。',:v,'same-model')"),
                      {'pid':self.pid,'rid':self.rid,'eid':self.eid,'uid':self.uid,'v':json.dumps([1.]+[0.]*1023)})

    def update(self,sql,params=None):
        with self.engine.begin()as c:
            c.exec_driver_sql('PRAGMA query_only=OFF');c.execute(text(sql),params or {})

    def load(self,**kw):
        with d.readonly(self.engine)as c:return d.load_run(c,self.uid,self.rid,**kw)

    def test_real_source_protocol_readonly_and_vector_parse(self):
        events,vs=self.load()
        self.assertEqual(['具体经历。'],d.array('["具体经历。"]'))
        self.assertEqual(self.eid,events[0]['id']);self.assertEqual(1024,len(vs[self.pid]['values']))
        with d.readonly(self.engine)as c:
            with self.assertRaises(Exception):c.execute(text("UPDATE users SET username='changed'"))
        with self.engine.connect()as c:self.assertEqual('isolated',c.execute(text('SELECT username FROM users')).scalar())

    def test_user_isolation_and_published_flag(self):
        with d.readonly(self.engine)as c:
            with self.assertRaises(w.WorkflowError):d.load_run(c,str(uuid4()),self.rid)
        with self.assertRaises(w.WorkflowError):self.load(published=True)
        self.update("UPDATE graph_runs SET status='PUBLISHED'")
        with self.assertRaises(w.WorkflowError):self.load(published=True)
        self.update('UPDATE diary_events SET is_in_graph=1')
        self.assertEqual(1,len(self.load(published=True)[0]))

    def test_changed_content_revision_and_digest(self):
        for sql in ["UPDATE diary_events SET body='[\"改动\"]'",
                    'UPDATE diaries SET is_dirty=1',
                    'UPDATE diary_organized SET structured_revision=2',
                    "UPDATE graph_runs SET source_sha256='wrong'"]:
            with self.subTest(sql=sql):
                with self.engine.connect()as c:
                    c.exec_driver_sql('PRAGMA query_only=OFF');transaction=c.begin_nested()
                    c.execute(text(sql))
                    with self.assertRaises(w.WorkflowError):d.load_run(c,self.uid,self.rid)
                    transaction.rollback()

    def test_low_and_unrated_events_are_loaded_and_cannot_be_silently_omitted(self):
        source=deepcopy(self.source)
        added=[]
        with self.engine.begin()as c:
            for i,importance in enumerate(('LOW',None),1):
                eid,pid=str(uuid4()),str(uuid4());added.append(eid)
                source['events'].append({**source['events'][0],'event_id':eid,'source_order':i,'importance':importance})
                c.execute(text("INSERT INTO diary_events VALUES(:eid,:oid,'同名事件',:body,'[]','[]',:i,NULL,:level,0)"),
                          {'eid':eid,'oid':self.oid,'body':json.dumps(['具体经历。']),'i':i,'level':importance})
                c.execute(text('INSERT INTO graph_run_events VALUES(:rid,:eid,:uid,:i,NULL)'),{'rid':self.rid,'eid':eid,'uid':self.uid,'i':i})
                c.execute(text("INSERT INTO graph_event_points SELECT :pid,run_id,:eid,user_id,no,summary,detail,embedding,embedding_model FROM graph_event_points WHERE id=:old"),
                          {'pid':pid,'eid':eid,'old':self.pid})
            c.execute(text('UPDATE graph_runs SET source_snapshot=:s,source_sha256=:h'),{'s':json.dumps(source),'h':w.digest(source)})
        events,vectors=self.load()
        self.assertEqual(3,len(events))
        self.assertTrue(all(not any('importance'in key for key in event)for event in events))
        self.assertEqual(3,len(w.prepare_data(events,[],vectors,w.settings())['pairs']))
        self.update("UPDATE graph_runs SET status='PUBLISHED'")
        self.update('UPDATE diary_events SET is_in_graph=1')
        self.assertEqual(3,len(self.load(published=True)[0]))
        self.update('DELETE FROM graph_run_events WHERE event_id=:eid',{'eid':added[0]})
        with self.assertRaisesRegex(w.WorkflowError,'全部来源事件'):self.load(published=True)

    def test_unrelated_metadata_changes_do_not_change_export(self):
        before=self.load()
        self.update("UPDATE diary_events SET user_importance='LOW',ai_importance=NULL")
        self.assertEqual(before,self.load())
        self.assertNotIn('importance',json.dumps(before,ensure_ascii=False))

    def test_missing_or_wrong_admission_node(self):
        self.update('DELETE FROM graph_run_events')
        with self.assertRaises(w.WorkflowError):self.load()

    def test_legacy_published_source_protocol(self):
        source={k:v for k,v in self.source.items()if k not in ('scope','content_revision','structured_revision')}
        source.update(original_text='原文',introduction='',trivia=[],plans=[])
        self.update('UPDATE graph_runs SET source_snapshot=:s,source_sha256=:h',{'s':json.dumps(source),'h':w.digest(source)})
        self.assertEqual(1,len(self.load()[0]))
        self.update("UPDATE diary_organized SET introduction='新引入'")
        with self.assertRaises(w.WorkflowError):self.load()

    def test_complete_prepare_does_not_load_other_user_or_ready_history(self):
        args=SimpleNamespace(backend_dir=Path('.'),username='isolated',date='2026-09-09',diary_id=None,
                             run_id=None,history_mode='published',completed_run=[])
        @contextmanager
        def isolated_connection(_):
            with d.readonly(self.engine)as c:yield c
        with patch.object(d,'connection',isolated_connection):s=d.prepare(args)
        self.assertEqual(1,len(s['events']));self.assertEqual([],s['pairs'])
        self.assertEqual('database',s['history_mode'])
        self.update('DELETE FROM graph_event_points')
        with patch.object(d,'connection',isolated_connection):
            with self.assertRaises(w.WorkflowError):d.prepare(args)

    def test_bad_json_array_stops_instead_of_counting_characters(self):
        for v in ('{"body":"text"}', 'not json', 1, [1]):
            with self.assertRaises(w.WorkflowError):d.array(v)

    def test_verify_receipt_and_changed_vector_are_not_silent(self):
        @contextmanager
        def isolated_connection(_):
            with d.readonly(self.engine)as c:yield c
        with tempfile.TemporaryDirectory()as root:
            events,vs=self.load();s=w.prepare_data(events,[],vs,w.settings());folder=w.write_package(s,root)
            w.render(folder);self.assertIsNone(w.read_json(folder/'resolved-results.json')['database_verification'])
            args=SimpleNamespace(run_dir=folder,backend_dir=Path('.'))
            with patch.object(d,'connection',isolated_connection):d.verify(args)
            w.render(folder);self.assertTrue(w.read_json(folder/'resolved-results.json')['database_verification']['verified_against_database'])
            self.update('UPDATE graph_event_points SET embedding=:v',{'v':json.dumps([0.,1.]+[0.]*1022)})
            with patch.object(d,'connection',isolated_connection):
                with self.assertRaises(w.WorkflowError):d.verify(args)
            self.assertFalse((folder/'verification.json').exists())

    def test_find_lists_run_ids_for_unambiguous_selection(self):
        with d.readonly(self.engine)as c:listing=d.list_diaries(c,'isolated','2026-09-09')
        self.assertEqual(self.rid,listing['diaries'][0]['runs'][0]['id'])


    def add_history(self, day, status='POINTS_READY', organized=True):
        ids={name:str(uuid4())for name in ('did','oid','eid','rid','pid')}
        source=deepcopy(self.source)
        source.update(diary_id=ids['did'],diary_date=day,organized_id=ids['oid'])
        source['events'][0]['event_id']=ids['eid']
        with self.engine.begin()as c:
            c.exec_driver_sql('PRAGMA query_only=OFF')
            for table,key in [('diaries','did'),('diary_organized','oid'),('diary_events','eid'),('graph_runs','rid'),('graph_event_points','pid')]:
                c.execute(text(f'INSERT INTO {table} SELECT * FROM {table} LIMIT 1'))
                c.execute(text(f'UPDATE {table} SET id=:new WHERE rowid=(SELECT max(rowid) FROM {table})'),{'new':ids[key]})
            c.execute(text('UPDATE diaries SET diary_date=:day,status=:status WHERE id=:did'),{**ids,'day':day,'status':'organized' if organized else 'saved'})
            c.execute(text('UPDATE diary_organized SET diary_id=:did WHERE id=:oid'),ids)
            c.execute(text('UPDATE diary_events SET diary_organized_id=:oid WHERE id=:eid'),ids)
            c.execute(text('UPDATE graph_runs SET diary_id=:did,diary_date=:day,status=:status,source_organized_id=:oid,source_snapshot=:source,source_sha256=:sha WHERE id=:rid'),
                {**ids,'day':day,'status':status,'source':json.dumps(source),'sha':w.digest(source)})
            c.execute(text('INSERT INTO graph_run_events VALUES(:rid,:eid,:uid,0,NULL)'),{**ids,'uid':self.uid})
            c.execute(text('UPDATE graph_event_points SET run_id=:rid,event_id=:eid WHERE id=:pid'),ids)
        return ids

    def test_database_history_cross_month_without_local_directories(self):
        self.add_history('2026-08-31')
        self.add_history('2026-09-01','PUBLISHED')
        self.add_history('2026-10-01') # future, never loaded
        self.add_history('2026-08-30',organized=False) # saved, never loaded
        with d.readonly(self.engine)as c:
            events,vs,inventory=d.database_history(c,self.uid,'2026-09-09')
        self.assertEqual(['2026-08-31','2026-09-01'],[e['diary_date']for e in events])
        self.assertEqual(2,len(inventory));self.assertEqual(2,len(vs))
        with d.readonly(self.engine)as c:
            self.assertEqual(([],{},[]),d.database_history(c,str(uuid4()),'2026-10-02'))

    def test_database_history_missing_or_ambiguous_points_rejected(self):
        ids=self.add_history('2026-09-01')
        self.update("UPDATE graph_runs SET status='FAILED' WHERE id=:rid",ids)
        with d.readonly(self.engine)as c:
            events,vs,inventory=d.database_history(c,self.uid,'2026-09-09')
        self.assertEqual([],events);self.assertEqual('NO_FORMAL_POINTS',inventory[0]['gap'])
        self.update("UPDATE graph_runs SET status='POINTS_READY' WHERE id=:rid",ids)
        self.update('INSERT INTO graph_runs SELECT * FROM graph_runs WHERE id=:rid',ids)
        with d.readonly(self.engine)as c:
            with self.assertRaisesRegex(w.WorkflowError,'多个有效运行'):
                d.database_history(c,self.uid,'2026-09-09')

    def test_database_inventory_verifies_unselected_event_and_new_history(self):
        ids=self.add_history('2026-09-01')
        # Orthogonal vector: valid history is present in inventory but absent from candidates.
        self.update('UPDATE graph_event_points SET embedding=:v WHERE id=:pid',
            {**ids,'v':json.dumps([0.,1.]+[0.]*1022)})
        @contextmanager
        def isolated_connection(_):
            with d.readonly(self.engine)as c:yield c
        args=SimpleNamespace(backend_dir=Path('.'),username='isolated',date='2026-09-09',diary_id=None,run_id=None)
        with patch.object(d,'connection',isolated_connection):snapshot=d.prepare(args)
        self.assertEqual(1,len(snapshot['events']));self.assertEqual(1,snapshot['history_selection']['event_count'])
        with tempfile.TemporaryDirectory()as root:
            folder=w.write_package(snapshot,root);args.run_dir=folder
            with patch.object(d,'connection',isolated_connection):d.verify(args)
            self.update("UPDATE graph_event_points SET detail='历史文字变更' WHERE id=:pid",ids)
            with patch.object(d,'connection',isolated_connection):
                with self.assertRaisesRegex(w.WorkflowError,'数据库历史范围'):d.verify(args)
            self.assertFalse((folder/'verification.json').exists())
            self.update("UPDATE graph_event_points SET detail='具体经历。' WHERE id=:pid",ids)
            with patch.object(d,'connection',isolated_connection):d.verify(args)
            self.add_history('2026-09-02')
            with patch.object(d,'connection',isolated_connection):
                with self.assertRaisesRegex(w.WorkflowError,'数据库历史范围'):d.verify(args)

    def test_cli_rejects_removed_history_switches(self):
        for extra in (['--history-mode','replay'],['--completed-run','/tmp/old']):
            with self.assertRaises(SystemExit)as caught:
                w.main(['prepare','--username','isolated','--date','2026-09-09',*extra])
            self.assertEqual(2,caught.exception.code)


if __name__=='__main__':unittest.main()
