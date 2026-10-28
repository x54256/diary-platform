"""隔离验证：同批当前节点、分支、间接留档和发布前强制复核；不访问远程库。"""
from copy import deepcopy
import json
from pathlib import Path
import unittest
from unittest.mock import patch

import workflow as w
import redundancy as r
from draft import parse_text, render_text
from test_workflow import event, vectors


class RedundancyTest(unittest.TestCase):
    def setup_graph(self, fork=False):
        a=event('2026-09-07');b=event('2026-09-08',uid=a['user_id'])
        c=event('2026-09-09'if fork else'2026-09-10',uid=a['user_id'])
        d=event('2026-09-10',uid=a['user_id'],rid=c['run_id'],did=c['diary_id']);d['source_order']=1
        current=[d]if fork else[c,d];history=[a,b,c]if fork else[a,b]
        snap=w.prepare_data(current,history,vectors(current+history),w.settings())
        self.ids={name:e['id'] for name,e in zip('ABCD',[a,b,c,d])}
        self.alias={e['id']:k for k,e in snap['events'].items()}
        self.keys={}
        rows=[]
        for pair in snap['pairs']:
            ea,eb=[snap['events'][pair[k]]for k in ('event_a','event_b')]
            ea,eb=sorted([ea,eb],key=lambda e:(e['diary_date'],e['source_order']))
            alias_a,alias_b=self.alias[ea['id']],self.alias[eb['id']]
            self.keys[(ea['id'],eb['id'])]=pair['pair_id']
            rows.append({'pair_id':pair['pair_id'],'status':'RELATED','reason':'同一事项的新进展。',
                         'relation':{'source_event':alias_a,'target_event':alias_b,'relation_type':'后续事件',
                                     'certainty':'EXPLICIT','description':'同一事项的新进展。',
                                     'source_evidence':[{'point_no':1,'quote':ea['points'][0]['detail']}],
                                     'target_evidence':[{'point_no':1,'quote':eb['points'][0]['detail']}]}})
        old=[{'edge_id':'H:AB','source':a['id'],'target':b['id'],'description':'A到B','evidence':[]}]
        if fork:old.append({'edge_id':'H:AC','source':a['id'],'target':c['id'],'description':'另一分支','evidence':[]})
        ctx=r.make_context(snap,rows,{'events':{e['id']:e for e in history},'edges':old})
        return snap,rows,ctx

    def key(self,a,b):return self.keys[(self.ids[a],self.ids[b])]
    def edge(self,a,b):return 'C:'+self.key(a,b)
    def decisions(self):
        return [{'pair_id':self.key(a,b),'decision':'INDIRECT_FOLLOWUP','reason':'模型核对同一事项且无独立承接。','replacement_path':path}
                for a,b,path in [('A','C',['H:AB',self.edge('B','C')]),
                                 ('A','D',['H:AB',self.edge('B','C'),self.edge('C','D')]),
                                 ('B','D',[self.edge('B','C'),self.edge('C','D')])]]

    def test_current_nodes_and_final_retained_paths(self):
        snap,rows,ctx=self.setup_graph()
        self.assertEqual({self.key('A','C'),self.key('A','D'),self.key('B','D')},{x['pair_id']for x in ctx['flagged']})
        final=r.final_rows(ctx,self.decisions())
        self.assertEqual(3,sum(x['status']=='INDIRECT_FOLLOWUP'for x in final))
        self.assertEqual(2,sum(x['status']=='RELATED'for x in final))
        self.assertEqual(final,parse_text(render_text(snap,final),snap))

    def test_cli_record_finalize_and_draft_roundtrip(self):
        import tempfile
        import contextlib
        import io
        snap,rows,ctx=self.setup_graph()
        snap['requires_redundancy_review']=True
        snap['package_sha256']=w.digest({k:v for k,v in snap.items()if k!='package_sha256'})
        ctx=r.make_context(snap,rows,ctx['history'])
        with tempfile.TemporaryDirectory()as tmp:
            folder=w.write_package(snap,Path(tmp))
            incoming=Path(tmp)/'initial.json'
            w.write_json(incoming,{'package_sha256':snap['package_sha256'],'results':rows})
            w.record(folder,incoming)
            with self.assertRaisesRegex(w.WorkflowError,'先完成'):w.render(folder)
            self.assertFalse((folder/'关系结果.md').exists())
            w.write_json(folder/r.CONTEXT,ctx)
            ds=Path(tmp)/'decisions.json'
            w.write_json(ds,{'context_sha256':ctx['context_sha256'],'decisions':self.decisions()})
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(0,r.main(['record',str(folder),'--input',str(ds)]))
                self.assertEqual(0,r.main(['read',str(folder),'--pair-id',self.key('A','D')]))
                self.assertEqual(0,r.main(['read',str(folder),'--edge-id','H:AB']))
                self.assertEqual(0,r.main(['finalize',str(folder)]))
            self.assertEqual(3,w.render(folder)['counts']['INDIRECT_FOLLOWUP'])
            self.assertEqual(3,sum(v['status']=='INDIRECT_FOLLOWUP'for v in w.saved_results(folder,snap)))
            self.assertTrue((folder/r.REPORT).exists())
            current=(folder/'关系结果.md').read_text()+'\n'
            (folder/'关系结果.md').write_text(current)
            with contextlib.redirect_stdout(io.StringIO()):self.assertEqual(0,r.main(['finalize',str(folder)]))
            self.assertEqual(current,(folder/'关系结果.md').read_text())

    def test_pending_review_cannot_finalize(self):
        _,_,ctx=self.setup_graph()
        with self.assertRaisesRegex(w.WorkflowError,'仍有待复核'):r.final_rows(ctx,self.decisions()[:1])

    def test_deleted_witness_requires_model_repair(self):
        _,_,ctx=self.setup_graph();ds=self.decisions()
        ds[1]['replacement_path']=['H:AB',self.edge('B','D')]
        r.validate_decisions(ctx,ds,complete=True)
        with self.assertRaisesRegex(w.WorkflowError,'退回模型'):r.final_rows(ctx,ds)

    def test_keep_despite_reachability(self):
        _,_,ctx=self.setup_graph();ds=self.decisions()
        for d in ds:d.update(decision='KEEP',replacement_path=[],reason='路径中途切换事项，不能替代直接承接。')
        final=r.final_rows(ctx,ds)
        self.assertTrue(all(v['status']=='RELATED'for v in final))

    def test_fork_preserves_both_direct_predecessors(self):
        _,_,ctx=self.setup_graph(fork=True)
        ds=[{'pair_id':self.key('A','D'),'decision':'INDIRECT_FOLLOWUP','reason':'分支已完整表达。',
             'replacement_path':['H:AB',self.edge('B','D')]}]
        final=r.final_rows(ctx,ds)
        self.assertEqual(2,sum(v['status']=='RELATED'for v in final))

    def test_invalid_paths_and_extra_decisions_rejected(self):
        _,_,ctx=self.setup_graph()
        for path in ([self.edge('A','D')],['missing','H:AB'],[self.edge('C','D'),'H:AB']):
            ds=self.decisions();ds[1]['replacement_path']=path
            with self.assertRaises(w.WorkflowError):r.validate_decisions(ctx,ds)
        ds=self.decisions();ds[0]['pair_id']=self.key('C','D')
        with self.assertRaises(w.WorkflowError):r.validate_decisions(ctx,ds)

    def test_context_and_final_draft_bound(self):
        snap,_,ctx=self.setup_graph();ds=self.decisions();rows=r.final_rows(ctx,ds)
        report={'context':ctx,'decisions':ds,'final_rows_sha256':w.digest(sorted(rows,key=lambda v:v['pair_id']))}
        r.check_report(snap,rows,report)
        bad=deepcopy(rows);bad[0]['reason']='用户改稿'
        with self.assertRaises(w.WorkflowError):r.check_report(snap,bad,report)
        bad=deepcopy(ctx);bad['flagged']=[]
        with self.assertRaises(w.WorkflowError):r.validate_context(snap,bad)

    def test_other_types_not_filtered(self):
        snap,rows,ctx=self.setup_graph()
        for v in rows:v['relation']['relation_type']='引发事件'
        ctx=r.make_context(snap,rows,ctx['history'])
        self.assertEqual([],ctx['flagged']);self.assertEqual(rows,r.final_rows(ctx,[]))

    def test_no_alternative_requires_no_semantic_decisions(self):
        snap,rows,ctx=self.setup_graph();rows=[v for v in rows if v['pair_id']==self.key('C','D')]
        snap=deepcopy(snap);snap['pairs']=[p for p in snap['pairs']if p['pair_id']==rows[0]['pair_id']]
        ctx=r.make_context(snap,rows,{'events':{},'edges':[]})
        self.assertEqual(rows,r.final_rows(ctx,[]))


class RedundancyStorageTest(unittest.TestCase):
    def setUp(self):
        import test_storage
        self.f=test_storage.StorageTest();self.f.setUp();self.addCleanup(self.f.doCleanups)
        self.snap,_=w.load_package(self.f.folder)
        self.ctx=r.make_context(self.snap,self.f.packet['results'],{'events':{},'edges':[]})
        w.write_json(self.f.folder/r.CONTEXT,self.ctx)

    def report(self):
        rows=r.final_rows(self.ctx,[])
        report={'context':self.ctx,'decisions':[],'final_rows_sha256':w.digest(sorted(rows,key=lambda v:v['pair_id']))}
        w.write_json(self.f.folder/r.REPORT,report)

    def test_missing_report_blocks_packet(self):
        import storage
        with self.assertRaisesRegex(w.WorkflowError,'先完成全部'):storage.build_packet(self.f.folder,'isolated')

    def test_report_standalone_publication_and_archive(self):
        import storage
        self.report();packet=storage.build_packet(self.f.folder,'isolated')
        # 保存使用独立包，不依赖本地复核文件。
        (self.f.folder/r.REPORT).unlink()
        result=self.f.transaction(packet)
        self.assertTrue(result['stored'])
        _,checkpoint,_,_=self.f.state()
        self.assertEqual(packet['redundancy'],checkpoint['skill_relations']['redundancy'])

    def test_history_growth_blocks_publication(self):
        import storage
        self.report();packet=storage.build_packet(self.f.folder,'isolated')
        self.f.fixture.add_history('2026-09-08')
        with self.assertRaises(w.WorkflowError):self.f.transaction(packet)
        from sqlalchemy import text
        with self.f.engine.connect()as conn:self.assertEqual(0,conn.execute(text('SELECT count(*) FROM graph_event_relations')).scalar())


if __name__=='__main__':unittest.main()
