import json,sys,time
from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo
ROOT=Path(__file__).resolve().parent
PROJECT=ROOT.parents[2]
sys.path.insert(0,str(PROJECT/'skills/diary-event-relations/scripts'))
import workflow as w
import db_source as db
from draft import read_draft
old=json.loads((PROJECT/'diary-event-relations/批次评估/2026-09-全量回放-20261023/execution.json').read_text())
dates=['2026-09-03','2026-09-09','2026-09-17','2026-09-20','2026-09-22','2026-09-23','2026-09-25','2026-09-27']
extras={'2026-09-23':[('a05e8164-781d-4187-bdbd-c2c00046eb5c','263d2593-9661-4814-a3e8-b7a3850e0a8b'),('34a6697e-050b-432f-8880-dc9686a074e0','3d3e1dc5-2f5e-41d7-8f14-966d405c642d')],'2026-09-27':[('08ebf16a-1744-46f7-9b44-a15778746ba7','402aa9a1-1768-4d08-b48a-44b1c27221ec')]}
def save(p,x):p.write_text(json.dumps(x,ensure_ascii=False,indent=2)+'\n')
state={'started_at':datetime.now(ZoneInfo('Asia/Shanghai')).isoformat(),'actual_host_tokens':None,'database_written':False,'days':[]}
for d in old['days']:
 if d['date']not in dates:continue
 start=time.perf_counter();f=Path(d['run_dir']);s=w.read_json(f/'source.json');_,rows=read_draft(f/'关系结果.md',s,complete=True)
 with db.connection(PROJECT/'backend')as conn:
  current,vectors=db.load_run(conn,s['user_id'],s['current_run_id'])
  history,vs,inventory=db.database_history(conn,s['user_id'],s['diary_date']);vectors.update(vs)
 cfg=w.settings();fresh=w.prepare_data(current,history,vectors,cfg,history_inventory=inventory)
 required=set()
 for p in s['pairs']:
  a=s['events'][p['event_a']];b=s['events'][p['event_b']]
  if a['diary_date']!=b['diary_date']:
   if a['run_id']==s['current_run_id']:required.add((a['id'],b['id']))
   else:required.add((b['id'],a['id']))
 required.update(extras.get(d['date'],[]))
 ranks=[];absent=[]
 for cid,hid in sorted(required):
  hits=next(r['hits']for r in fresh['recall']if r['current_event_id']==cid)
  hit=next(((i,h)for i,h in enumerate(hits,1)if h['event_id']==hid),None)
  if not hit or hit[1]['score']<cfg['min_similarity']:absent.append([cid,hid])
  else:ranks.append(hit[0])
 assert not absent, '原审核范围中的历史事件已不满足召回阈值，需单独核实'
 cfg['top_k']=max([cfg['top_k'],*ranks])
 if cfg!=fresh['config']:raise AssertionError('unexpected shared config')
 # prepare_data stores config by reference; reconstruct so digest matches enlarged candidate rule.
 fresh=w.prepare_data(current,history,vectors,cfg,history_inventory=inventory)
 folder=w.write_package(fresh)
 old_by_ids={tuple(sorted([s['events'][p['event_a']]['id'],s['events'][p['event_b']]['id']])):r for p,r in zip(s['pairs'],rows)}
 old_events={e['id']:e for e in s['events'].values()};new_events={e['id']:e for e in fresh['events'].values()}
 changed=[eid for eid in old_events if eid in new_events and old_events[eid]!=new_events[eid]]
 same=[];new=[];import copy
 for p in fresh['pairs']:
  ids=tuple(sorted(fresh['events'][p[k]]['id']for k in ('event_a','event_b')))
  row=old_by_ids.get(ids)
  if row and not any(eid in changed for eid in ids):
   row=copy.deepcopy(row)
   if row['relation']:
    for k in ('source_event','target_event'):
     eid=s['events'][row['relation'][k]]['id'];row['relation'][k]=next(a for a,e in fresh['events'].items()if e['id']==eid)
   same.append(row)
  else:new.append(p)
 save(ROOT/(d['date']+'-复用判断.json'),{'package_sha256':fresh['package_sha256'],'results':same})
 save(ROOT/(d['date']+'-新增候选.json'),{'pairs':new,'events':fresh['events']})
 item={'date':d['date'],'old_run_dir':str(f),'run_dir':str(folder),'top_k':cfg['top_k'],'old_pairs':len(s['pairs']),'new_pairs':len(fresh['pairs']),'reusable':len(same),'new_or_changed':len(new),'changed_old_event_ids':changed,'prepare_seconds':time.perf_counter()-start,'history_selection':fresh['history_selection']}
 state['days'].append(item);save(ROOT/'execution.json',state)
 print(json.dumps({k:v for k,v in item.items()if k not in ['history_selection','old_run_dir']},ensure_ascii=False),flush=True)
