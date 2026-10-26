import json,sys
from pathlib import Path
R=Path(__file__).resolve().parent
state=json.loads((R/'execution.json').read_text());events={};pairs=[]
for d in state['days']:
 p=json.loads((R/(d['date']+'-新增候选.json')).read_text())
 for pair in p['pairs']:
  ids=[p['events'][pair[k]]['id']for k in ('event_a','event_b')]
  events.update({i:next(e for e in p['events'].values()if e['id']==i)for i in ids})
  pairs.append({'date':d['date'],'pair_id':pair['pair_id'],'event_ids':ids})
ordered=sorted(events.values(),key=lambda e:(e['diary_date'],e['source_order'],e['id']));aliases={e['id']:f'G{i:03}'for i,e in enumerate(ordered,1)}
(R/'新增配对与事件.json').write_text(json.dumps({'events':{aliases[e['id']]:e for e in ordered},'pairs':[{**p,'aliases':[aliases[i]for i in p['event_ids']]}for p in pairs]},ensure_ascii=False,indent=2)+'\n')
if len(sys.argv)==1:
 print('events',len(ordered),'pairs',len(pairs))
 for i,e in enumerate(ordered,1):print(i,e['diary_date'],e['title'],sum(len(p['detail'])for p in e['points']))
else:
 a,b=map(int,sys.argv[1:3])
 for e in ordered[a-1:b]:
  print(aliases[e['id']],e['diary_date'],e['title'])
  for p in e['points']:print('P'+str(p['no']),p['detail'])
