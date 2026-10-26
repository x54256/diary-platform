import copy
import json
from pathlib import Path
import tempfile
import unittest
from uuid import uuid4

import workflow as w


def event(day='2026-09-09', *, uid=None, rid=None, did=None, detail='我预约了周五的检查。'):
    return {'id':str(uuid4()),'user_id':uid or str(uuid4()),'run_id':rid or str(uuid4()),
            'diary_id':did or str(uuid4()),'diary_date':day,'title':'相同标题','source_order':0,
            'importance':'MEDIUM','occurred_on':None,'run_status':'POINTS_READY',
            'run_source_sha256':'a'*64,
            'points':[{'id':str(uuid4()),'no':1,'summary':'检查安排','detail':detail}]}


def vectors(events, score=None):
    return {p['id']:{'model':'isolated-model','values':[1.,0.]+[0.]*1022}
            for e in events for p in e['points']}


class WorkflowTest(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
        self.a=event();self.b=event(uid=self.a['user_id'],rid=self.a['run_id'],did=self.a['diary_id'],detail='今天按预约完成检查。')
        self.b['source_order']=1
        self.config=w.settings()

    def prepare(self,current=None,history=None,config=None,completed=()):
        current=current if current is not None else [self.a,self.b];history=history or []
        return w.prepare_data(current,history,vectors(current+history),config or self.config,history_mode='replay',completed=completed)

    def result(self,s,status='RELATED'):
        pair=s['pairs'][0];aliases=list(s['events'])
        a,b=aliases[0],aliases[1]
        rel={'source_event':a,'target_event':b,'relation_type':'后续事件','certainty':'EXPLICIT',
             'source_evidence':[{'point_no':1,'quote':s['events'][a]['points'][0]['detail']}],
             'target_evidence':[{'point_no':1,'quote':s['events'][b]['points'][0]['detail']}],
             'description':'预约的检查得到执行。'} if status=='RELATED' else None
        return {'package_sha256':s['package_sha256'],'results':[{'pair_id':pair['pair_id'],'status':status,
                'reason':'检查安排得到执行。' if status=='RELATED' else '未发现双方有具体联系。','relation':rel}]}

    def test_partial_resume_revision_and_idempotent_render(self):
        s=self.prepare();folder=w.write_package(s,self.root);incoming=self.root/'incoming.json'
        self.assertFalse(w.progress(s,[],w.read_json(folder/'run.json'))['complete'])
        with self.assertRaises(w.WorkflowError):w.render(folder)
        w.write_json(incoming,self.result(s));self.assertTrue(w.record(folder,incoming)['complete'])
        w.render(folder);before=(folder/'results.json').read_bytes()
        w.record(folder,incoming)
        self.assertEqual(before,(folder/'results.json').read_bytes());self.assertTrue((folder/'关系结果.md').exists())
        changed=self.result(s,'NO_RELATION');w.write_json(incoming,changed)
        with self.assertRaises(w.WorkflowError):w.record(folder,incoming)
        w.record(folder,incoming,replace=True)
        self.assertTrue(list(folder.glob('results-backup-*')))
        self.assertFalse((folder/'关系结果.md').exists());self.assertTrue(list(folder.glob('关系结果-previous-*')))
        w.render(folder);self.assertFalse(w.read_json(folder/'resolved-results.json')['stored_in_database'])

    def test_all_importance_levels_and_unrated_participate(self):
        for current_level in ('LOW',None,'MEDIUM','HIGH'):
            with self.subTest(importance=current_level):
                a=copy.deepcopy(self.a);b=copy.deepcopy(self.b)
                a['importance']=current_level;b['importance']='LOW'
                history=event('2026-09-08',uid=a['user_id']);history['importance']=None
                snapshot=self.prepare([a,b],[history])
                self.assertEqual(3,len(snapshot['events']))
                self.assertEqual(3,len(snapshot['pairs']))
                self.assertNotIn('importance',json.dumps(snapshot,ensure_ascii=False))
                self.assertEqual(2,len(snapshot['recall']))
                self.assertTrue(all(r['selected_event_ids']==[history['id']]for r in snapshot['recall']))

    def test_cross_user_and_future_rejected(self):
        for h in (event('2026-09-08'),event('2026-09-10',uid=self.a['user_id'])):
            with self.assertRaises(w.WorkflowError):self.prepare(history=[h])

    def test_invalid_vectors_and_model_mismatch(self):
        for values in ([1.], [0.]*1024, [float('nan')]+[0.]*1023, [True]+[0.]*1023):
            with self.assertRaises(w.WorkflowError):w.validate_vector(values)
        v=vectors([self.a,self.b]);v[self.b['points'][0]['id']]['model']='other'
        with self.assertRaises(w.WorkflowError):w.prepare_data([self.a,self.b],[],v,self.config)

    def test_aggregate_before_top_k_and_stable_order(self):
        current=event('2026-09-10',uid=self.a['user_id'])
        history=[event(uid=current['user_id'])for _ in range(13)]
        for _ in range(10):
            no=len(history[0]['points'])+1
            history[0]['points'].append({'id':str(uuid4()),'no':no,'summary':'相近要点','detail':'同一历史事件的额外信息。'})
        for k in (5, self.config['top_k']):
            with self.subTest(top_k=k):
                s=self.prepare([current],history,config={**self.config,'top_k':k,'retain_all_min_similarity':None})
                self.assertEqual(k,len(s['pairs']))
                self.assertEqual(sorted(e['id']for e in history)[:k],s['recall'][0]['selected_event_ids'])
                self.assertEqual(13,len(s['recall'][0]['hits']))

    def test_top_k_union_high_scores_inclusive_and_deduplicated(self):
        hits=[{'event_id':str(i),'score':score} for i,score in enumerate(
            [.8]*11 + [.5,.499,.4,.399])]
        selected=w.select_history_hits(hits,self.config)
        self.assertEqual([str(i) for i in range(12)],[h['event_id']for h in selected])
        self.assertEqual(12,len({h['event_id']for h in selected}))
        # With fewer high scores, lower scores may still enter through Top K.
        hits=[{'event_id':str(i),'score':score} for i,score in enumerate(
            [.6,.5]+[.49]*10+[.399])]
        selected=w.select_history_hits(hits,self.config)
        self.assertEqual([str(i)for i in range(6)],[h['event_id']for h in selected])
        self.assertEqual(2,len(w.select_history_hits(hits[:2],self.config)))

    def test_high_score_union_aggregates_event_points_before_selection(self):
        current=event('2026-09-10',uid=self.a['user_id'])
        history=[event(uid=current['user_id'])for _ in range(13)]
        for _ in range(3):
            history[0]['points'].append({'id':str(uuid4()),'no':len(history[0]['points'])+1,
                'summary':'同一事件补充','detail':'不会占用多个事件名额。'})
        s=self.prepare([current],history)
        self.assertEqual(13,len(s['pairs']))
        self.assertEqual(sorted(e['id']for e in history),s['recall'][0]['selected_event_ids'])

    def test_threshold_and_no_padding(self):
        current=event('2026-09-10',uid=self.a['user_id']);h=event(uid=current['user_id'])
        v=vectors([current,h]);v[h['points'][0]['id']]['values']=[0.,1.]+[0.]*1022
        s=w.prepare_data([current],[h],v,self.config)
        self.assertEqual([],s['pairs']);self.assertEqual([],s['recall'][0]['selected_event_ids'])

    def test_batch_dedup_complete_and_single_pair_budget(self):
        c=event(uid=self.a['user_id'],rid=self.a['run_id'],did=self.a['diary_id']);c['source_order']=2
        config={**self.config,'max_pairs_per_batch':2}
        s=self.prepare([self.a,self.b,c],config=config);bs=w.batches(s)
        self.assertEqual([2,1],[len(b['pair_ids'])for b in bs])
        self.assertEqual(3,len(bs[0]['payload']['events']))
        self.assertEqual(len(s['pairs']),sum(len(b['pair_ids'])for b in bs))
        small={**self.config,'max_batch_chars':1}
        s=self.prepare(config=small)
        with self.assertRaises(w.WorkflowError):w.write_package(s,self.root)
        self.assertEqual([],list(self.root.iterdir()))

    def test_extra_duplicate_wrong_package_rejected_atomically(self):
        s=self.prepare();folder=w.write_package(s,self.root);incoming=self.root/'input.json'
        good=self.result(s)
        bads=[]
        b=copy.deepcopy(good);b['results']*=2;bads.append(b)
        b=copy.deepcopy(good);b['results'][0]['pair_id']='extra';bads.append(b)
        b=copy.deepcopy(good);b['package_sha256']='bad';bads.append(b)
        b=copy.deepcopy(good);b['results'][0]['relation']['target_event']='E999';bads.append(b)
        for b in bads:
            w.write_json(incoming,b)
            with self.assertRaises(w.WorkflowError):w.record(folder,incoming)
            self.assertFalse((folder/'results.json').exists())

    def test_evidence_wrong_point_fabrication_and_ambiguity(self):
        s=self.prepare();good=self.result(s)
        for item in ({'point_no':True,'quote':'我预约了周五的检查。'}, {'point_no':2,'quote':'我预约了周五的检查。'},
                     {'point_no':1,'quote':'我已经完成手术。'}):
            b=copy.deepcopy(good);b['results'][0]['relation']['source_evidence']=[item]
            with self.assertRaises(w.WorkflowError):w.check_rows(s,b)
        a=copy.deepcopy(self.a);a['points'][0]['detail']='好。好。'
        s=self.prepare([a,self.b]);b=self.result(s)
        b['results'][0]['relation']['source_evidence'][0]['quote']='好。'
        with self.assertRaises(w.WorkflowError):w.check_rows(s,b)

    def test_skill_change_allows_existing_package_but_batch_tampering_fails(self):
        from unittest.mock import patch
        s=self.prepare();folder=w.write_package(s,self.root)
        with patch.object(w,'skill_fingerprint',return_value='changed'):
            loaded,_=w.load_package(folder)
            self.assertEqual(s['package_sha256'],loaded['package_sha256'])
        (folder/'B001.json').write_text('{}')
        with self.assertRaises(w.WorkflowError):w.load_package(folder)

    def test_empty_candidates_render_without_synthetic_result(self):
        s=self.prepare([self.a]);folder=w.write_package(s,self.root)
        self.assertTrue(w.render(folder)['complete'])
        self.assertEqual([],w.read_json(folder/'resolved-results.json')['results'])

    def test_dependency_changed_invalidates_next_day(self):
        first=self.prepare();folder=w.write_package(first,self.root)
        incoming=self.root/'first.json';w.write_json(incoming,self.result(first,'NO_RELATION'));w.record(folder,incoming)
        rows=w.saved_results(folder,first)
        dep={'run_dir':str(folder),'package_sha256':first['package_sha256'],'results_sha256':w.digest(rows)}
        next_event=event('2026-09-10',uid=self.a['user_id'])
        second=self.prepare([next_event],completed=[dep]);second_folder=w.write_package(second,self.root)
        w.load_package(second_folder)
        changed=self.result(first,'UNRESOLVED');w.write_json(incoming,changed);w.record(folder,incoming,replace=True)
        with self.assertRaises(w.WorkflowError):w.load_package(second_folder)

    def test_duplicate_json_field_rejected(self):
        p=self.root/'bad.json';p.write_text('{"results":[],"results":[]}')
        with self.assertRaises(w.WorkflowError):w.read_json(p)


if __name__=='__main__':unittest.main()
