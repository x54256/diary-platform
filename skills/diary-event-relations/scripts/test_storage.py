"""隔离 SQLite 验证发布事务；不连接项目数据库。"""
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest
from uuid import uuid4

from sqlalchemy import text

import storage as s
import workflow as w
import test_db_source


class StorageTest(unittest.TestCase):
    def setUp(self):
        self.fixture=test_db_source.DatabaseSourceTest();self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.engine=self.fixture.engine
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
        f=self.fixture
        with self.engine.begin()as c:
            for sql in [
                "ALTER TABLE graph_runs ADD COLUMN checkpoint TEXT DEFAULT '{}'",
                'ALTER TABLE graph_runs ADD COLUMN published_at TEXT',
                'ALTER TABLE graph_runs ADD COLUMN updated_at TEXT',
                'ALTER TABLE graph_runs ADD COLUMN current_step TEXT',
                'CREATE TABLE graph_tasks(id TEXT,user_id TEXT,status TEXT)',
                'CREATE TABLE organize_tasks(id TEXT,user_id TEXT,status TEXT)',
                "CREATE TABLE graph_event_relations(id TEXT PRIMARY KEY,run_id TEXT,user_id TEXT,source_run_id TEXT,source_event_id TEXT,target_run_id TEXT,target_event_id TEXT,relation_type TEXT,certainty TEXT,description TEXT,final_source TEXT,created_at TEXT,CONSTRAINT ck_graph_relation_description CHECK(length(trim(description))>0 AND final_source IN ('AGREEMENT','ADJUDICATED','SKILL_AGENT')))",
                'CREATE TABLE graph_relation_evidence(relation_id TEXT,side TEXT,point_id TEXT,user_id TEXT,source_run_id TEXT,source_event_id TEXT,target_run_id TEXT,target_event_id TEXT,point_run_id TEXT,point_event_id TEXT)']:
                c.exec_driver_sql(sql)
            events=deepcopy(f.source['events'])
            for i in (1,2):
                eid,pid=str(uuid4()),str(uuid4())
                e={**events[0],'event_id':eid,'source_order':i};events.append(e)
                c.execute(text("INSERT INTO diary_events VALUES(:eid,:oid,'同名事件',:body,'[]','[]',:i,NULL,'MEDIUM',0)"),{'eid':eid,'oid':f.oid,'body':json.dumps(e['body']),'i':i})
                c.execute(text('INSERT INTO graph_run_events VALUES(:rid,:eid,:uid,:i,NULL)'),{'rid':f.rid,'eid':eid,'uid':f.uid,'i':i})
                c.execute(text("INSERT INTO graph_event_points SELECT :pid,run_id,:eid,user_id,no,summary,detail,embedding,embedding_model FROM graph_event_points WHERE id=:old"),{'pid':pid,'eid':eid,'old':f.pid})
            source={**f.source,'events':events}
            c.execute(text('UPDATE graph_runs SET source_snapshot=:source,source_sha256=:sha,checkpoint=:cp'),{'source':json.dumps(source),'sha':w.digest(source),'cp':json.dumps({'points_stage':'preserved'})})
        events,vs=f.load()
        snapshot=w.prepare_data(events,[],vs,w.settings())
        self.folder=w.write_package(snapshot,self.root)
        aliases=list(snapshot['events']);rows=[]
        for pair,status in zip(snapshot['pairs'],('RELATED','NO_RELATION','UNRESOLVED')):
            a,b=(snapshot['events'][pair[k]]for k in ('event_a','event_b'))
            rel={'source_event':pair['event_a'],'target_event':pair['event_b'],'relation_type':'后续事件','certainty':'EXPLICIT',
                 'description':'具体事项出现后续进展。','source_evidence':[{'point_no':1,'quote':a['points'][0]['detail']}],
                 'target_evidence':[{'point_no':1,'quote':b['points'][0]['detail']}]}if status=='RELATED'else None
            rows.append({'pair_id':pair['pair_id'],'status':status,'reason':'合成事务测试判断。','relation':rel})
        path=self.root/'input.json';w.write_json(path,{'package_sha256':snapshot['package_sha256'],'results':rows});w.record(self.folder,path)
        w.render(self.folder)
        self.packet=s.build_packet(self.folder,'isolated')

    def transaction(self,packet=None,sha=None):
        packet=packet or self.packet
        with self.engine.begin()as c:
            c.exec_driver_sql('PRAGMA query_only=OFF')
            return s.publish(c,packet,'isolated',sha or packet['storage_sha256'])

    def state(self):
        with self.engine.connect()as c:
            row=c.execute(text('SELECT status,checkpoint FROM graph_runs')).one()
            return row[0],json.loads(row[1]),c.execute(text('SELECT count(*) FROM graph_event_relations')).scalar(),c.execute(text('SELECT count(*) FROM graph_relation_evidence')).scalar()

    def history_packet(self):
        f=self.fixture
        ids=f.add_history('2026-09-08')
        current,vs=f.load()
        with self.engine.connect()as c:
            history,hv=s.load_run(c,f.uid,ids['rid'])
        snap=w.prepare_data(current,history,{**vs,**hv},w.settings())
        folder=w.write_package(snap,self.root)
        rows=[]
        for pair in snap['pairs']:
            a,b=(snap['events'][pair[k]] for k in ('event_a','event_b'))
            relation=None
            if a['run_id']!=b['run_id']:
                relation={'source_event':pair['event_a'],'target_event':pair['event_b'],
                    'relation_type':'后续事件','certainty':'EXPLICIT','description':'隔离测试的跨日关系。',
                    'source_evidence':[{'point_no':1,'quote':a['points'][0]['detail']}],
                    'target_evidence':[{'point_no':1,'quote':b['points'][0]['detail']}]}
            rows.append({'pair_id':pair['pair_id'],'status':'RELATED' if relation else 'NO_RELATION',
                         'reason':'隔离测试。','relation':relation})
        incoming=self.root/'history-input.json'
        w.write_json(incoming,{'package_sha256':snap['package_sha256'],'results':rows})
        w.record(folder,incoming);w.render(folder)
        return ids,s.build_packet(folder,'isolated')

    def test_unpublished_history_allows_cross_day_publication(self):
        ids,packet=self.history_packet()
        with self.engine.connect()as c:
            state=s.inspect_target(c,packet,'isolated')
        self.assertEqual([],state['missing_published_dependencies'])
        self.assertEqual(3,state['relations'])
        self.assertTrue(self.transaction(packet)['stored'])
        with self.engine.connect()as c:
            self.assertEqual('POINTS_READY',c.execute(text('SELECT status FROM graph_runs WHERE id=:id'),{'id':ids['rid']}).scalar())

    def test_unpublished_history_changed_vector_still_blocks_publication(self):
        ids,packet=self.history_packet()
        self.fixture.update('UPDATE graph_event_points SET embedding=:v WHERE id=:pid',
                            {'pid':ids['pid'],'v':json.dumps([0.,1.]+[0.]*1022)})
        with self.assertRaises(w.WorkflowError):self.transaction(packet)
        with self.engine.connect()as c:
            self.assertEqual(0,c.execute(text('SELECT count(*) FROM graph_event_relations')).scalar())

    def test_readonly_returns_connection_without_leaking_query_only(self):
        with s.readonly(self.engine)as c:
            with self.assertRaises(Exception):c.exec_driver_sql("UPDATE users SET username='wrong'")
        with self.engine.begin()as c:
            self.assertEqual(0,c.exec_driver_sql('PRAGMA query_only').scalar())
            self.assertTrue(s.publish(c,self.packet,'isolated',self.packet['storage_sha256'])['stored'])

    def test_skill_change_allows_packet_validation_and_isolated_publication(self):
        from unittest.mock import patch
        with patch.object(w,'skill_fingerprint',return_value='changed'):
            s.validate_packet(self.packet)
            rebuilt=s.build_packet(self.folder,'isolated')
            self.assertEqual(self.packet['skill_sha256'],rebuilt['skill_sha256'])
            self.assertTrue(self.transaction()['stored'])

    def test_publish_all_judgments_idempotent_preserves_points(self):
        s.validate_packet(self.packet)
        with self.engine.connect()as c:before=c.execute(text('SELECT * FROM graph_event_points ORDER BY id')).all()
        self.assertTrue(self.transaction()['stored'])
        status,cp,edges,evidence=self.state()
        self.assertEqual(('PUBLISHED',1,2),(status,edges,evidence));self.assertEqual('preserved',cp['points_stage'])
        archive=cp['skill_relations'];self.assertEqual({'RELATED','NO_RELATION','UNRESOLVED'},{r['status']for r in archive['results']})
        self.assertEqual(self.packet['results_sha256'],archive['results_sha256'])
        self.transaction();self.assertEqual((1,2),self.state()[2:])
        with self.engine.connect()as c:self.assertEqual(before,c.execute(text('SELECT * FROM graph_event_points ORDER BY id')).all())

    def test_failed_evidence_insert_rolls_back_everything(self):
        self.fixture.update("CREATE TRIGGER fail_evidence BEFORE INSERT ON graph_relation_evidence BEGIN SELECT RAISE(ABORT,'isolated failure'); END")
        with self.assertRaises(Exception):self.transaction()
        self.assertEqual(('POINTS_READY',{'points_stage':'preserved'},0,0),self.state())
        with self.engine.connect()as c:self.assertEqual(0,c.execute(text('SELECT sum(is_in_graph) FROM diary_events')).scalar())

    def test_readonly_preview_and_ownership(self):
        with s.readonly(self.engine)as c:
            self.assertFalse(s.inspect_target(c,self.packet,'isolated')['stored'])
            with self.assertRaises(w.WorkflowError):s.inspect_target(c,self.packet,'other')
        self.assertEqual('POINTS_READY',self.state()[0])
        with self.assertRaises(w.WorkflowError):self.transaction(sha='wrong')
        self.assertEqual(0,self.state()[2])

    def test_revised_results_bound_to_new_hash_and_no_overwrite(self):
        altered=deepcopy(self.packet);altered['results'][0]['reason']='修订了判断说明。'
        with self.assertRaises(w.WorkflowError):s.validate_packet(altered)
        from draft import render_text,text_sha
        altered['draft']['content']=render_text(altered['snapshot'],altered['results']);altered['draft']['sha256']=text_sha(altered['draft']['content'])
        altered['resolved_results']=s.resolve(altered['snapshot'],altered['results'])
        altered['results_sha256']=s.result_digest(altered['snapshot'],altered['resolved_results'])
        altered['storage_sha256']=w.digest({k:v for k,v in altered.items()if k!='storage_sha256'})
        s.validate_packet(altered);self.assertNotEqual(self.packet['results_sha256'],altered['results_sha256'])
        self.transaction()
        with self.assertRaises(w.WorkflowError):self.transaction(altered)
        self.assertEqual(1,self.state()[2])

    def test_standalone_packet_after_local_folder_removed(self):
        import shutil
        shutil.rmtree(self.folder)
        self.assertTrue(self.transaction()['stored'])

    def test_changed_source_vector_or_active_task_refused(self):
        mutations=["UPDATE graph_event_points SET detail='变化'", "UPDATE graph_event_points SET embedding='[]'",
                   "INSERT INTO graph_tasks VALUES('task',:uid,'RUNNING')", "INSERT INTO organize_tasks VALUES('task',:uid,'running')"]
        for sql in mutations:
            with self.subTest(sql=sql), self.engine.connect()as c:
                c.exec_driver_sql('PRAGMA query_only=OFF');tx=c.begin_nested()
                c.execute(text(sql),{'uid':self.fixture.uid})
                with self.assertRaises(w.WorkflowError):s.publish(c,self.packet,'isolated',self.packet['storage_sha256'])
                tx.rollback()
        self.assertEqual('POINTS_READY',self.state()[0])

    def test_zero_relationship_publication_still_archives(self):
        p=deepcopy(self.packet)
        for row in p['results']:row.update(status='NO_RELATION',relation=None)
        from draft import render_text,text_sha
        p['draft']['content']=render_text(p['snapshot'],p['results']);p['draft']['sha256']=text_sha(p['draft']['content'])
        p['resolved_results']=s.resolve(p['snapshot'],p['results']);p['results_sha256']=s.result_digest(p['snapshot'],p['resolved_results'])
        p['storage_sha256']=w.digest({k:v for k,v in p.items()if k!='storage_sha256'})
        self.transaction(p);self.assertEqual(('PUBLISHED',0,0),(self.state()[0],*self.state()[2:]))
        self.assertEqual(3,len(self.state()[1]['skill_relations']['results']))

    def revised_packet(self):
        from draft import render_text,text_sha
        p=deepcopy(self.packet)
        row=next(r for r in p['results']if r['relation'])
        row['relation']['description']='同一具体事项出现了修订后的新进展。'
        p['draft']['content']=render_text(p['snapshot'],p['results'])
        p['draft']['sha256']=text_sha(p['draft']['content'])
        p['resolved_results']=s.resolve(p['snapshot'],p['results'])
        p['results_sha256']=s.result_digest(p['snapshot'],p['resolved_results'])
        p['storage_sha256']=w.digest({k:v for k,v in p.items()if k!='storage_sha256'})
        return p

    def replace_transaction(self,packet):
        with self.engine.begin()as c:
            c.exec_driver_sql('PRAGMA query_only=OFF')
            return s.publish(c,packet,'isolated',packet['storage_sha256'],
                             replace_published=True,accept_published_revisions=True)

    def test_explicit_replacement_archives_old_edges_and_is_idempotent(self):
        self.transaction();old=self.state();p=self.revised_packet()
        self.assertTrue(self.replace_transaction(p)['stored'])
        state=self.state();self.assertEqual((1,2),state[2:])
        history=state[1]['skill_relations_history']
        self.assertEqual(1,len(history))
        self.assertEqual(old[1]['skill_relations'],history[0]['archive'])
        self.assertEqual(1,len(history[0]['relations']))
        self.assertEqual(2,len(history[0]['evidence']))
        self.assertEqual(p['storage_sha256'],state[1]['skill_relations']['storage_sha256'])
        self.replace_transaction(p)
        self.assertEqual(state,self.state())

    def test_replacement_evidence_failure_rolls_back_deletion_and_archive(self):
        self.transaction();before=self.state();p=self.revised_packet()
        self.fixture.update("CREATE TRIGGER fail_replace BEFORE INSERT ON graph_relation_evidence BEGIN SELECT RAISE(ABORT,'isolated replacement failure'); END")
        with self.assertRaises(Exception):self.replace_transaction(p)
        self.assertEqual(before,self.state())

    def test_replacement_does_not_bypass_changed_facts(self):
        self.transaction();before=self.state();p=self.revised_packet()
        self.fixture.update("UPDATE graph_event_points SET detail='来源已经变化'")
        with self.assertRaises(w.WorkflowError):self.replace_transaction(p)
        self.assertEqual(before,self.state())


if __name__=='__main__':unittest.main()
