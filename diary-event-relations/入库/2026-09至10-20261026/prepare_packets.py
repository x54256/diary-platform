"""按用户已授权的当前稿准备独立入库包与只读预检。无数据库写操作。"""
import sys,json,time
from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo
ROOT=Path(__file__).resolve().parent;PROJECT=ROOT.parents[2]
sys.path.insert(0,str(PROJECT/'skills/diary-event-relations/scripts'))
import workflow as w
import storage as st
import db_source as db
from draft import text_sha
now=lambda:datetime.now(ZoneInfo('Asia/Shanghai')).isoformat()
prior=w.read_json(ROOT/'预检.json')
state={'started_at':now(),'user_authorization':'使用skill将9月和10月所有关系稿入库；用户明确不以旧版本验证阻塞，全部按当前稿入库','publication_options':{'replace_published':True,'accept_published_revisions':True},'database_written':False,'model_calls':0,'days':[]}
for d in prior['days']:
 folder=Path(d['run_dir']);packet=st.build_packet(folder,'x5456');st.validate_packet(packet)
 assert packet['draft']['sha256']==d['draft_sha256'],'主稿在用户授权后发生变化，停止'
 path=ROOT/(d['date']+'-入库包-'+packet['storage_sha256'][:16]+'.json')
 if path.exists():assert w.read_json(path)==packet
 else:w.write_json(path,packet)
 state['days'].append({'date':d['date'],'draft':d['draft'],'run_id':packet['current_run_id'],'packet':str(path),'storage_sha256':packet['storage_sha256'],'results_sha256':packet['results_sha256'],'draft_sha256':packet['draft']['sha256'],'relations':sum(r['status']=='RELATED'for r in packet['results']),'pairs':len(packet['results'])})
w.write_json(ROOT/'入库执行清单.json',state)
with db.connection(PROJECT/'backend')as conn:
 uid=packet['user_id']
 def points_digest():
  r=db.query(conn,"SELECT count(*) AS count, md5(string_agg(md5(to_jsonb(p)::text),'' ORDER BY p.id)) AS sha FROM graph_event_points p WHERE p.user_id=:uid",{'uid':uid})[0]
  return dict(r)
 state['points_before']=points_digest()
 assert st.schema_ready(conn),'数据库缺少所需来源约束'
 assert not db.query(conn,"SELECT id FROM graph_tasks WHERE user_id=:uid AND status IN ('QUEUED','RUNNING')",{'uid':uid}),'存在活动图谱任务'
 assert not db.query(conn,"SELECT id FROM organize_tasks WHERE user_id=:uid AND status='running'",{'uid':uid}),'存在活动整理任务'
 for d in state['days']:
  packet=w.read_json(Path(d['packet']));t=time.perf_counter()
  result=st.inspect_target(conn,packet,'x5456',replace_published=True,accept_published_revisions=True)
  d['preflight']=result;d['preflight_seconds']=time.perf_counter()-t
  if result['run_status']=='PUBLISHED':
   _,checkpoint,_=st.archive_for(conn,packet);w.write_json(ROOT/(d['date']+'-原发布checkpoint.json'),checkpoint)
  print(d['date'],d['relations'],result['run_status'],'missing_history',len(result['missing_published_dependencies']),flush=True)
state['preflight_completed_at']=now();w.write_json(ROOT/'入库执行清单.json',state)
print('PACKETS_READY',len(state['days']),sum(d['relations']for d in state['days']),flush=True)
