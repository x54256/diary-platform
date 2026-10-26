import json,sys,time
from datetime import datetime
from zoneinfo import ZoneInfo
from pathlib import Path
from types import SimpleNamespace
ROOT=Path(__file__).resolve().parent;PROJECT=ROOT.parents[2]
sys.path.insert(0,str(PROJECT/'skills/diary-event-relations/scripts'))
import workflow as w
import db_source as db
from draft import read_draft

def now():return datetime.now(ZoneInfo('Asia/Shanghai')).isoformat()
state=w.read_json(ROOT/'execution.json')
logpath=ROOT/'workflow-log.json';logs=w.read_json(logpath)if logpath.exists()else []
def call(name,date,fn):
 started=now();t=time.perf_counter()
 try:result=fn()
 except Exception as exc:
  logs.append({'date':date,'command':name,'started_at':started,'ended_at':now(),'seconds':time.perf_counter()-t,'success':False,'error_type':type(exc).__name__});w.write_json(logpath,logs)
  print('STOP',date,name,type(exc).__name__,flush=True);raise SystemExit(1)
 logs.append({'date':date,'command':name,'started_at':started,'ended_at':now(),'seconds':time.perf_counter()-t,'success':True,'result':result});w.write_json(logpath,logs)
 return result
for day in state['days']:
 folder=Path(day['run_dir']);s,m=w.load_package(folder)
 # 留存完整批次读取负载；语义阅读使用同一来源的完整详情和明确配对，不打印重复负载。
 if not day.get('read_recorded'):
  payloads=[w.payload(s,[p for p in s['pairs']if p['pair_id']in b['pair_ids']])for b in m['batches']]
  w.write_json(ROOT/(day['date']+'-读取批次.json'),payloads)
  day['read_chars']=sum(len(json.dumps(p,ensure_ascii=False,separators=(',',':')))for p in payloads);day['read_recorded']=True;w.write_json(ROOT/'execution.json',state)
 call('record',day['date'],lambda:w.record(folder,ROOT/(day['date']+'-最终判断.json'),replace=True))
 def check():
  s,m=w.load_package(folder);r=w.saved_results(folder,s);result=w.progress(s,r,m);assert result['complete'];return result
 call('check',day['date'],check)
 call('verify',day['date'],lambda:db.verify(SimpleNamespace(run_dir=folder,backend_dir=PROJECT/'backend')))
 call('render',day['date'],lambda:w.render(folder))
 _,rows=read_draft(folder/'关系结果.md',s,complete=True)
 from collections import Counter
 day.update(complete=True,completed_at=now(),counts=dict(Counter(r['status']for r in rows)))
 w.write_json(ROOT/'execution.json',state)
 print(day['date'],day['counts'],flush=True)
state['finished_at']=now();w.write_json(ROOT/'execution.json',state)
