"""仅清点并预检现有关系稿；不执行迁移、发布或模型调用。"""
import sys,json,hashlib,time
from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo
ROOT=Path(__file__).resolve().parent;PROJECT=ROOT.parents[2]
sys.path.insert(0,str(PROJECT/'skills/diary-event-relations/scripts'))
import workflow as w
import storage as st
import db_source as db
from draft import read_draft
stamp=lambda:datetime.now(ZoneInfo('Asia/Shanghai')).isoformat()
selected={}
for d in w.read_json(PROJECT/'diary-event-relations/修订/2026-09-审阅采信修订-20261026/当前稿件索引.json')['days']:selected[d['date']]=d
for d in w.read_json(PROJECT/'diary-event-relations/批次评估/2026-09至10-跨月补处理-20261026/运行清单.json'):selected[d['date']]=d
report={'started_at':stamp(),'database_written':False,'model_calls':0,'current_skill_sha256':w.skill_fingerprint(),'days':[]}
for date,d in sorted(selected.items()):
 f=Path(d['run_dir']);s=w.read_json(f/'source.json');_,rows=read_draft(f/'关系结果.md',s,complete=True)
 from collections import Counter
 item={'date':date,'diary_id':s['diary_id'],'run_id':s['current_run_id'],'run_dir':str(f),'draft':str(f/'关系结果.md'),'draft_sha256':hashlib.sha256((f/'关系结果.md').read_bytes()).hexdigest(),'source_skill_sha256':s['skill_sha256'],'history_mode':s['history_mode'],'counts':dict(Counter(r['status']for r in rows))}
 try:
  packet=st.build_packet(f,'x5456');path=ROOT/(date+'-入库包.json');w.write_json(path,packet);item.update(packet=str(path),local_preflight='PASS')
 except w.WorkflowError as e:item.update(local_preflight='BLOCKED',local_reason=str(e))
 report['days'].append(item)
w.write_json(ROOT/'预检.json',report)
print('local',len(report['days']),'packages',sum(d['local_preflight']=='PASS'for d in report['days']),flush=True)
try:
 with db.connection(PROJECT/'backend')as conn:
  report['schema']=st.schema(conn)
  uid=selected and w.read_json(Path(next(iter(selected.values()))['run_dir'])/'source.json')['user_id']
  runs=db.query(conn,"""SELECT r.id,r.diary_date,r.status,
   (SELECT count(*)FROM graph_event_relations g WHERE g.run_id=r.id) AS relations
   FROM graph_runs r WHERE r.user_id=:uid AND r.status IN ('POINTS_READY','PUBLISHED') ORDER BY r.diary_date,r.id""",{'uid':uid})
  report['database_runs']=[{'id':str(r['id']),'date':str(r['diary_date']),'status':r['status'],'relations':r['relations']}for r in runs]
  status={r['id']:r for r in report['database_runs']}
  for d in report['days']:
   d['database_target']=status.get(d['run_id']);s=w.read_json(Path(d['run_dir'])/'source.json')
   if d['database_target']and d['database_target']['status']=='PUBLISHED':
    _,_,archive=st.archive_for(conn,{'user_id':uid,'current_run_id':d['run_id']})
    archived=archive.get('results',[])if archive else []
    _,current=read_draft(Path(d['draft']),s,complete=True)
    d['existing_publication']={'archive_present':bool(archive),'schema_version':archive.get('schema_version')if archive else None,'archived_pairs':len(archived),'archived_related':sum(r.get('status')=='RELATED'for r in archived),'current_related':sum(r['status']=='RELATED'for r in current),'archived_source_sha256':archive.get('source_package_sha256')if archive else None,'current_source_sha256':s['package_sha256'],'same_source_package':bool(archive and archive.get('source_package_sha256')==s['package_sha256'])}
   histids={e['run_id']for e in s['events'].values()}-{s['current_run_id']}
   d['unpublished_history']=[status.get(rid,{'id':rid,'status':'NOT_ACTIVE'})for rid in sorted(histids)if status.get(rid,{}).get('status')!='PUBLISHED']
  report['database_readonly_preflight']='COMPLETE'
except Exception as e:
 report['database_readonly_preflight']='BLOCKED';report['database_error_type']=type(e).__name__;print('database',type(e).__name__,flush=True)
report['finished_at']=stamp();w.write_json(ROOT/'预检.json',report)
print('summary',report.get('schema'),report['database_readonly_preflight'],flush=True)
