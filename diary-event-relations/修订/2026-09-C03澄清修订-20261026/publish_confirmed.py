"""按用户确认，原子替换两份新整稿；使用skill发布器，保留旧归档。"""
import argparse,sys,hashlib,time
from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo
ROOT=Path(__file__).resolve().parent;PROJECT=ROOT.parents[2]
sys.path.insert(0,str(PROJECT/'skills/diary-event-relations/scripts'))
import workflow as w
import storage as st
import db_source as db
now=lambda:datetime.now(ZoneInfo('Asia/Shanghai')).isoformat()
pre=w.read_json(ROOT/'入库预检.json');days=pre['days'];manifest=[{k:d[k]for k in ('date','storage_sha256','after_sha256','relations')}for d in days];sha=w.digest(manifest)
a=argparse.ArgumentParser();a.add_argument('--write',action='store_true');a.add_argument('--confirmed-manifest');args=a.parse_args()
if not args.write:print(sha);raise SystemExit(0)
w.require(args.confirmed_manifest==sha,'确认批次指纹不匹配')
original=PROJECT/'diary-event-relations/入库/2026-09至10-20261026';state=w.read_json(original/'入库执行清单.json');prior={d['date']:d for d in state['days']}
packets=[]
for d in days:
 p=st.validate_packet(w.read_json(Path(d['packet'])));w.require(p['storage_sha256']==d['storage_sha256'],'入库包变化')
 w.require(hashlib.sha256(Path(d['draft']).read_bytes()).hexdigest()==d['after_sha256']==p['draft']['sha256'],'确认后的稿件已变化')
 packets.append(p)
uid=packets[0]['user_id'];report={'started_at':now(),'authorization':'确认，按两份新稿更新入库','manifest_sha256':sha,'database_written':False,'transaction':'one_atomic_transaction_for_two_revised_drafts','model_api_calls':0,'days':[]};path=ROOT/'发布结果.json';w.write_json(path,report);t=time.perf_counter()
def digest_points(c):return dict(db.query(c,"SELECT count(*) AS count, md5(string_agg(md5(to_jsonb(p)::text),'' ORDER BY p.id)) AS sha FROM graph_event_points p WHERE p.user_id=:uid",{'uid':uid})[0])
try:
 with db.backend_engine(PROJECT/'backend').begin()as conn:
  db.query(conn,'SELECT id FROM users WHERE id=:uid FOR UPDATE',{'uid':uid})
  before=digest_points(conn)
  for d,p in zip(days,packets):
   status,checkpoint,archive=st.archive_for(conn,p)
   w.require(status=='PUBLISHED'and archive is not None,'原发布状态不符合确认范围')
   w.require(archive['storage_sha256']in (prior[d['date']]['storage_sha256'],p['storage_sha256']),'原发布在确认后被其他操作替换')
   backup=ROOT/(d['date']+'-原发布checkpoint.json')
   if not backup.exists():w.write_json(backup,checkpoint)
   result=st.publish(conn,p,'x5456',p['storage_sha256'],replace_published=True,accept_published_revisions=True)
   report['days'].append({'date':d['date'],'storage_sha256':p['storage_sha256'],'relations':d['relations'],'result':result})
   w.write_json(path,report);print(d['date'],'STAGED',d['relations'],flush=True)
  w.require(digest_points(conn)==before,'要点或向量意外变化，回滚')
 report.update(database_written=True,committed_at=now(),seconds=time.perf_counter()-t,points_unchanged=True,points_before=before);w.write_json(path,report)
except Exception as exc:
 report.update(database_written=False,rolled_back=True,error_type=type(exc).__name__)
 if isinstance(exc,w.WorkflowError):report['reason']=str(exc)
 w.write_json(path,report);print('ROLLED_BACK',type(exc).__name__,report.get('reason',''),flush=True);raise SystemExit(1)
# 发布之后生成包含其余33份未变化稿的全量核验清单。
new={d['date']:d for d in days}
for d in state['days']:
 if d['date']in new:
  n=new[d['date']];d.update(packet=n['packet'],storage_sha256=n['storage_sha256'],draft_sha256=n['after_sha256'],relations=n['relations'])
state.update(points_before=before,database_written=True,latest_confirmation='确认，按两份新稿更新入库',latest_committed_at=report['committed_at'])
w.write_json(ROOT/'入库执行清单.json',state)
print('COMMITTED_TWO; expected whole batch = 335 relations, 0 unresolved',flush=True)
