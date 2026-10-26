"""以冻结召回排名及磁盘当前关系稿评估；不重算向量、不改判断或业务数据。"""
from pathlib import Path
import json,sys,collections,random,csv
PROJECT=Path(__file__).resolve().parents[3];OUT=Path(__file__).resolve().parent
ROOT=PROJECT/'diary-event-relations/批次评估/2026-09至10-跨月补处理-20261026'
sys.path.insert(0,str(PROJECT/'skills/diary-event-relations/scripts'))
from draft import read_draft
from workflow import digest
runs=json.loads((ROOT/'运行清单.json').read_text());corpus={};judged={};universe={};daily=[];allrows=[];gold={}
def key(a,b):return tuple(sorted((a,b)))
for item in runs:
 f=Path(item['run_dir']);s=json.loads((f/'source.json').read_text());_,rows=read_draft(f/'关系结果.md',s)
 corpus.update({e['id']:e for e in s['events'].values()});byid={p['pair_id']:p for p in s['pairs']};c=collections.Counter()
 for row in rows:
  pair=byid[row['pair_id']];a,b=[s['events'][pair[k]]for k in ['event_a','event_b']];k=key(a['id'],b['id']);scope='same_day'if a['diary_date']==b['diary_date']else'history'
  obj={'date':item['date'],'key':k,'scope':scope,'status':row['status'],'row':row};judged[k]=obj;allrows.append(obj);c[(scope,'candidates')]+=1;c[(scope,row['status'])]+=1
  if row['status']=='RELATED':gold[k]={'origin':'CURRENT_AGENT_JUDGMENT','row':row,'date':item['date'],'scope':scope}
 for rec in s['recall']:
  for rank,h in enumerate(rec['hits'],1):
   k=key(rec['current_event_id'],h['event_id']);assert k not in universe
   universe[k]={'date':item['date'],'key':k,'current_event_id':rec['current_event_id'],'historic_event_id':h['event_id'],'score':h['score'],'rank':rank,'selected':h['event_id']in rec['selected_event_ids']}
 daily.append({'date':item['date'],'same_day_candidates':c[('same_day','candidates')],'same_day_relations':c[('same_day','RELATED')],'history_candidates':c[('history','candidates')],'history_relations':c[('history','RELATED')],'history_pool':sum(len(x['hits'])for x in s['recall']),'current_events':len(s['recall'])})
for d in json.loads((ROOT/'旧正例退出候选.json').read_text()):
 rel=d['judgment']['relation'];a,b=[d['events'][rel[k]]for k in ['source_event','target_event']];corpus.update({e['id']:e for e in d['events'].values()});k=key(a['id'],b['id']);assert k not in gold;gold[k]={'origin':'PREVIOUS_AGENT_POSITIVE_OUTSIDE_TOP5','row':d['judgment'],'date':d['current_date'],'scope':'history'}
# User confirmed the later half-skimmed order; it is a diagnostic positive, not a formal stored edge.
a=next(e for e in corpus.values()if e['diary_date']=='2026-10-18'and e['title']=='用比价的方式给我爸再买两箱舒化奶');b=next(e for e in corpus.values()if e['diary_date']=='2026-10-22'and e['title']=='我妈嫌我们花钱多，讲消费占比还是讲不通');k=key(a['id'],b['id']);assert k not in gold;gold[k]={'origin':'USER_CONFIRMED_REFERENCE_NOT_IN_DRAFT','row':None,'date':'2026-10-22','scope':'history'}
# Independent blind positives explicitly accepted after main reread of both full point sets.
audit_labels={}
review=OUT/'主审采纳.json'
if review.exists():
 accepted=json.loads(review.read_text());samplemap={x['sample_id']:x for x in json.loads((OUT/'抽样清单-含分层.json').read_text())}
 for filename in ['未召回样本独立盲审.json','阈值降低新增候选盲审.json']:
  data=json.loads((OUT/filename).read_text())
  mappings=samplemap if filename.startswith('未召回') else {x['sample_id']:x for x in json.loads((OUT/'阈值降低新增候选.json').read_text())}
  for row in data['judgments']:
   u=mappings[row['sample_id']];k=key(u['current_event_id'],u['historic_event_id']);audit_labels[k]=row['status']
   if row['status']=='RELATED' and row['sample_id']in accepted['accepted_positive_ids']:
    gold[k]={'origin':'INDEPENDENT_BLIND_POSITIVE_MAIN_ACCEPTED','row':row,'date':u['date'],'scope':'history'}
reference={k:g for k,g in gold.items()if g['scope']=='history'};knownmiss=[]
for k,g in reference.items():
 u=universe[k]
 if not u['selected']:knownmiss.append({**u,'origin':g['origin'],'current_title':corpus[u['current_event_id']]['title'],'historic_title':corpus[u['historic_event_id']]['title'],'historic_date':corpus[u['historic_event_id']]['diary_date'],'rejection':'BELOW_THRESHOLD'if u['score']<.4 else'TOP5'})
counts={scope:{'candidates':sum(x['scope']==scope for x in allrows),'relations':sum(x['scope']==scope and x['status']=='RELATED'for x in allrows)}for scope in ['same_day','history']}
for v in counts.values():v['yield']=v['relations']/v['candidates']
base={'daily':daily,'all_counts':counts,'all_candidates':len(allrows),'all_relations':sum(x['status']=='RELATED'for x in allrows),'history_pool':len(universe),'history_above_04':sum(u['score']>=.4 for u in universe.values()),'history_rejected_threshold':sum(u['score']<.4 for u in universe.values()),'history_rejected_top5':sum(u['score']>=.4 and not u['selected']for u in universe.values()),'known_history_reference':len(reference),'known_current_history_positive':sum(g['origin']=='CURRENT_AGENT_JUDGMENT'for g in reference.values()),'known_misses':knownmiss,'gold_origins':dict(collections.Counter(g['origin']for g in gold.values()))}
sweeps=[]
for threshold in [.30,.35,.40,.45,.50,.55,.60]:
 for topk in [5,10,15,20,25,None]:
  selected={k for k,u in universe.items()if u['score']>=threshold and (topk is None or u['rank']<=topk)}
  pos=selected&reference.keys();observed=selected&judged.keys();known_negative={k for k in observed if judged[k]['status']=='NO_RELATION'}
  sweeps.append({'threshold':threshold,'top_k':topk,'history_candidates':len(selected),'known_positive_hit':len(pos),'known_positive_reference_size':len(reference),'known_positive_coverage':len(pos)/len(reference),'known_negative_hit':len(known_negative | {k for k in selected if audit_labels.get(k)=='NO_RELATION'}),'not_yet_semantically_judged':len(selected-set(gold)-set(judged)-set(audit_labels))})
bins=[]
for lo,hi in [(0,.30),(.30,.35),(.35,.40),(.40,.45),(.45,.50),(.50,.55),(.55,.60),(.60,1.000001)]:
 vals=[u for u in universe.values()if lo<=u['score']<hi];sel=[u for u in vals if u['selected']];pos=sum(key(*u['key'])in reference for u in vals)
 bins.append({'score_from':lo,'score_to':hi,'all_history_pairs':len(vals),'selected':len(sel),'selected_related':sum(judged[tuple(u['key'])]['status']=='RELATED'for u in sel),'known_reference_positive':pos})
# Blind stratified audit: only previously unjudged pairs, sampled from all ranks without title filtering.
rng=random.Random(20261026);sample=[];used=set();percurrent=collections.Counter()
for label,lo,hi,limit in [('B1',.30,.35,6),('B2',.35,.40,10),('B3',.40,.50,10),('B4',.50,1.000001,6)]:
 pool=[u for k,u in universe.items()if lo<=u['score']<hi and not u['selected']and k not in gold and k not in judged];rng.shuffle(pool);chosen=[]
 for u in pool:
  if percurrent[u['current_event_id']]>=2:continue
  chosen.append(u);percurrent[u['current_event_id']]+=1
  if len(chosen)==limit:break
 for u in chosen:sample.append({'sample_id':f"A{len(sample)+1:02}",'stratum':label,**u})
if (OUT/'抽样清单-含分层.json').exists():sample=json.loads((OUT/'抽样清单-含分层.json').read_text())
base['score_bins']=bins;base['parameter_sweeps']=sweeps;base['sample_design']={'seed':20261026,'size':len(sample),'strata':{'B1':'0.30–0.35未召回','B2':'0.35–0.40未召回','B3':'0.40–0.50未召回','B4':'>=0.50未召回'},'max_pairs_per_current_event':2,'reference_is_not_exhaustive_gold':True}
(OUT/'召回统计.json').write_text(json.dumps(base,ensure_ascii=False,indent=2));
if not (OUT/'抽样清单-含分层.json').exists():(OUT/'抽样清单-含分层.json').write_text(json.dumps(sample,ensure_ascii=False,indent=2))
(OUT/'已知事件语料.json').write_text(json.dumps(corpus,ensure_ascii=False,indent=2))
with (OUT/'全历史排名.csv').open('w')as f:
 writer=csv.DictWriter(f,fieldnames=['date','current_event_id','historic_event_id','score','rank','selected','judgment']);writer.writeheader()
 for k,u in universe.items():writer.writerow({**{x:u[x]for x in writer.fieldnames if x in u},'judgment':judged[k]['status']if k in judged else gold[k]['origin']if k in gold else audit_labels[k]if k in audit_labels else'NOT_JUDGED'})
print(json.dumps({k:v for k,v in base.items()if k not in ['daily','parameter_sweeps','score_bins']},ensure_ascii=False,indent=2))
print('SWEEPS',json.dumps([x for x in sweeps if x['threshold']in [.35,.4,.45]and x['top_k']in [5,10,20,None]],ensure_ascii=False))
