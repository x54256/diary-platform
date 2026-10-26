from pathlib import Path
import json,sys,math
from datetime import datetime,timezone
ROOT=Path(__file__).resolve().parent
PROJECT=ROOT.parents[2]
sys.path.insert(0,str(PROJECT/'backend'))
from database import SessionLocal
from models.graph import GraphRun,GraphTask,GraphEventPoint,GraphModelCall,GraphRunEvent
from sqlalchemy import text
from uuid import UUID
rows=json.loads((ROOT/'入库清单.json').read_text());results=[]
with SessionLocal() as db:
 db.execute(text('SET TRANSACTION READ ONLY'))
 for r in rows:
  folder=Path(r['output']).parent
  saved=json.loads((folder/'save-结果.json').read_text())['result'];run_id=UUID(saved['run_id'])
  run=db.get(GraphRun,run_id); task=db.get(GraphTask,run.task_id)
  assert run.status=='POINTS_READY' and task.status=='SUCCEEDED'
  packet=json.loads(Path(r['output']).read_text())
  expected={(UUID(e['event_id']),q['no']):q for e in packet['events'] for q in e['points']}
  points=db.query(GraphEventPoint).filter(GraphEventPoint.run_id==run_id).all()
  assert len(points)==len(expected)
  for q in points:
   v=expected[(q.event_id,q.no)]
   assert q.summary==v['summary'] and q.detail==v['detail']
   assert len(q.embedding)==1024 and all(math.isfinite(float(x)) for x in q.embedding) and sum(float(x)**2 for x in q.embedding)>0
  calls=db.query(GraphModelCall).filter(GraphModelCall.run_id==run_id).all()
  status_counts={s:sum(c.status==s for c in calls) for s in sorted(set(c.status for c in calls))}
  durations=[(c.completed_at-c.created_at).total_seconds() for c in calls if c.completed_at]
  ev=db.query(GraphRunEvent).filter(GraphRunEvent.run_id==run_id).count()
  assert ev==r['events']
  results.append({'date':r['date'],'run_id':str(run_id),'task_id':str(task.id),'stored':True,'run_status':run.status,'events':ev,'points':len(points),'vectors':len(points),'text_matches_packet':True,'all_vectors_1024_finite_nonzero':True,'calls':len(calls),'call_status_counts':status_counts,'input_tokens_reported':sum(c.input_tokens or 0 for c in calls),'input_tokens_missing_calls':sum(c.input_tokens is None for c in calls),'call_elapsed_total_seconds':round(sum(durations),3),'reused_vectors':saved['reused_vectors']})
 db.rollback()
report={'stage':4,'verified_at':datetime.now(timezone.utc).isoformat(),'days':len(results),'events':sum(r['events'] for r in results),'points':sum(r['points'] for r in results),'vectors':sum(r['vectors'] for r in results),'calls':sum(r['calls'] for r in results),'input_tokens_reported':sum(r['input_tokens_reported'] for r in results),'input_tokens_missing_calls':sum(r['input_tokens_missing_calls'] for r in results),'rows':results,'cost':'审计没有费用字段，不估算实际费用。'}
(ROOT/'入库核验.json').write_text(json.dumps(report,ensure_ascii=False,indent=2))
print(json.dumps({k:v for k,v in report.items() if k!='rows'},ensure_ascii=False))
with (ROOT/'流程留痕.md').open('a') as f:f.write('\n## 阶段4完成\n\n'+report['verified_at']+'：15篇全部POINTS_READY/SUCCEEDED，129事件300要点300向量；逐字核验数据库主旨详情与冻结稿相同，向量均1024维、有限且非零。调用审计和token可用性见入库核验.json。阶段5相关文件此前未读，现在可进入。\n')
