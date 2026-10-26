from pathlib import Path
import json,csv,collections
ROOT=Path(__file__).resolve().parent
s=json.loads((ROOT/'召回统计.json').read_text());rows=list(csv.DictReader((ROOT/'全历史排名.csv').open()))
assert len(rows)==s['history_pool']==25334
selected=[r for r in rows if r['selected']=='True'];assert len(selected)==671
assert sum(r['judgment']=='RELATED'for r in selected)==143
assert all((float(r['score'])>=.4 and int(r['rank'])<=5)==(r['selected']=='True')for r in rows)
assert len(s['known_misses'])==11 and all(u['rank']>5 and u['score']>=.4 for u in s['known_misses'])
assert s['known_history_reference']==154
for t in s['parameter_sweeps']:
 actual=sum(float(r['score'])>=t['threshold'] and (t['top_k']is None or int(r['rank'])<=t['top_k'])for r in rows)
 assert actual==t['history_candidates']
inputs={}
for p in (ROOT/'盲审输入与原始输出').glob('batch-*.json'):
 for row in json.loads(p.read_text()):assert row['sample_id']not in inputs;inputs[row['sample_id']]=row
for row in json.loads((ROOT/'盲审输入与原始输出/additional.json').read_text()):assert row['sample_id']not in inputs;inputs[row['sample_id']]=row
judgments=[]
for filename in ['未召回样本独立盲审.json','阈值降低新增候选盲审.json']:judgments+=json.loads((ROOT/filename).read_text())['judgments']
assert len(inputs)==len(judgments)==36 and {r['sample_id']for r in judgments}==inputs.keys()
for row in judgments:
 assert row['full_points_read']and row['status']in ['RELATED','NO_RELATION','UNRESOLVED']
 if row['status']=='RELATED':
  for proof in row['relation']['evidence']:
   e=inputs[row['sample_id']]['event_a'if proof['side']=='A'else'event_b'];point=next(p for p in e['points']if p['no']==proof['point_no']);assert point['detail'].count(proof['quote'])==1
counts=dict(collections.Counter(r['status']for r in judgments));assert counts=={'NO_RELATION':34,'RELATED':2}
result={'all_ranking_rows':len(rows),'actual_selected':len(selected),'actual_selected_related':143,'parameter_combinations_verified':len(s['parameter_sweeps']),'known_omissions_verified':11,'blind_pairs':36,'blind_counts':counts,'positive_quotes_unique':True,'production_data_changed':False}
(ROOT/'评估核验.json').write_text(json.dumps(result,ensure_ascii=False,indent=2));print(json.dumps(result,ensure_ascii=False))
