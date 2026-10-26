"""使用 skill 的发布事务保存已授权的35份当前稿；不调用模型。"""
import sys,json,time,argparse,hashlib
from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo
ROOT=Path(__file__).resolve().parent;PROJECT=ROOT.parents[2]
sys.path.insert(0,str(PROJECT/'skills/diary-event-relations/scripts'))
import workflow as w
import storage as st
import db_source as db
now=lambda:datetime.now(ZoneInfo('Asia/Shanghai')).isoformat()
state=w.read_json(ROOT/'入库执行清单.json')
manifest=[{k:d[k]for k in ('date','packet','storage_sha256','draft_sha256','relations')}for d in state['days']]
manifest_sha=w.digest(manifest)
a=argparse.ArgumentParser();a.add_argument('--write',action='store_true');a.add_argument('--confirmed-manifest');args=a.parse_args()
if not args.write:print(manifest_sha);raise SystemExit(0)
w.require(args.confirmed_manifest==manifest_sha,'批次指纹不匹配')
packets=[]
for d in state['days']:
 p=st.validate_packet(w.read_json(Path(d['packet'])))
 w.require(p['storage_sha256']==d['storage_sha256'],'入库包已改变')
 w.require(hashlib.sha256(Path(d['draft']).read_bytes()).hexdigest()==d['draft_sha256'],'当前稿已改变')
 packets.append(p)
uid=packets[0]['user_id'];w.require(all(p['user_id']==uid for p in packets),'批次跨用户')
report={'started_at':now(),'manifest_sha256':manifest_sha,'database_written':False,'transaction':'one_atomic_transaction_for_35_drafts','options':{'replace_published':True,'accept_published_revisions':True},'model_calls':0,'staged_days':[]}
path=ROOT/'发布结果.json';w.write_json(path,report)
t=time.perf_counter()
def digest_points(conn):
 return dict(db.query(conn,"SELECT count(*) AS count, md5(string_agg(md5(to_jsonb(p)::text),'' ORDER BY p.id)) AS sha FROM graph_event_points p WHERE p.user_id=:uid",{'uid':uid})[0])
try:
 with db.backend_engine(PROJECT/'backend').begin()as conn:
  # 用户行锁覆盖整个批次，防止另一任务在两篇保存之间穿插改源。
  db.query(conn,'SELECT id FROM users WHERE id=:uid FOR UPDATE',{'uid':uid})
  before=digest_points(conn);w.require(before==state['points_before'],'准备后正式要点已改变')
  for d,p in zip(state['days'],packets):
   started=time.perf_counter()
   result=st.publish(conn,p,'x5456',p['storage_sha256'],replace_published=True,accept_published_revisions=True)
   report['staged_days'].append({'date':d['date'],'packet':d['packet'],'storage_sha256':p['storage_sha256'],'relations':d['relations'],'seconds':time.perf_counter()-started,'result':result})
   w.write_json(path,report);print(d['date'],'STAGED',d['relations'],flush=True)
  w.require(digest_points(conn)==before,'要点或向量发生意外变化，回滚')
 report.update(database_written=True,committed_at=now(),seconds=time.perf_counter()-t,relations=sum(d['relations']for d in state['days']),points_unchanged=True)
 w.write_json(path,report);print('COMMITTED',len(packets),report['relations'],flush=True)
except Exception as exc:
 report.update(database_written=False,rolled_back=True,failed_at=now(),error_type=type(exc).__name__)
 if isinstance(exc,w.WorkflowError):report['reason']=str(exc)
 w.write_json(path,report);print('ROLLED_BACK',type(exc).__name__,report.get('reason',''),flush=True);raise SystemExit(1)
