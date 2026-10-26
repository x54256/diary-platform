"""只读逐篇核验发布结果、证据、完整判断、旧归档和要点指纹。"""
import sys,json
from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo
ROOT=Path(__file__).resolve().parent;PROJECT=ROOT.parents[2]
sys.path.insert(0,str(PROJECT/'skills/diary-event-relations/scripts'))
import workflow as w
import storage as st
import db_source as db
state=w.read_json(ROOT/'入库执行清单.json');publication=w.read_json(ROOT/'发布结果.json')
w.require(publication.get('database_written'),'本批尚未提交，拒绝生成成功回执')
checks=[]
with db.connection(PROJECT/'backend')as conn:
 for d in state['days']:
  p=st.validate_packet(w.read_json(Path(d['packet'])),current_skill=False);uid=p['user_id']
  status,checkpoint,archive=st.archive_for(conn,p)
  assert status=='PUBLISHED'and archive['storage_sha256']==p['storage_sha256'],d['date']
  assert archive['draft']['sha256']==p['draft']['sha256']
  assert archive['results']==p['resolved_results']
  edges=db.query(conn,'SELECT * FROM graph_event_relations WHERE run_id=:rid AND user_id=:uid',{'rid':p['current_run_id'],'uid':uid})
  byid={str(r['id']):r for r in edges};expected_evidence=set()
  for row in p['resolved_results']:
   if not row['relation']:continue
   rel=row['relation'];rid=archive['relation_ids'][row['pair_id']];actual=byid[rid]
   for k in ('source_run_id','source_event_id','target_run_id','target_event_id','relation_type','certainty','description'):assert str(actual[k])==str(rel[k]),(d['date'],k)
   assert actual['final_source']=='SKILL_AGENT'
   for side in ('source','target'):
    for proof in rel[side+'_evidence']:expected_evidence.add((rid,side.upper(),proof['point_id'],proof['point_run_id'],proof['point_event_id']))
  assert len(byid)==d['relations']==len(archive['relation_ids'])
  evidence=db.query(conn,'''SELECT e.* FROM graph_relation_evidence e JOIN graph_event_relations r ON r.id=e.relation_id
       WHERE r.run_id=:rid AND r.user_id=:uid''',{'rid':p['current_run_id'],'uid':uid})
  actual_evidence={(str(r['relation_id']),r['side'],str(r['point_id']),str(r['point_run_id']),str(r['point_event_id']))for r in evidence}
  assert actual_evidence==expected_evidence and len(evidence)==len(expected_evidence),d['date']
  old=ROOT/(d['date']+'-原发布checkpoint.json')
  old_preserved=None
  if old.exists():
   prior=w.read_json(old);history=checkpoint['skill_relations_history'];assert history[-1]['archive']==prior['skill_relations'];old_preserved={'history_entries':len(history),'old_relations':len(history[-1]['relations']),'old_evidence':len(history[-1]['evidence'])}
  checks.append({'date':d['date'],'stored':True,'status':status,'relations':len(edges),'evidence':len(evidence),'archived_judgments':len(archive['results']),'storage_sha256':archive['storage_sha256'],'draft_sha256':archive['draft']['sha256'],'old_publication_preserved':old_preserved})
  print(d['date'],'VERIFIED',len(edges),flush=True)
 points=dict(db.query(conn,"SELECT count(*) AS count, md5(string_agg(md5(to_jsonb(p)::text),'' ORDER BY p.id)) AS sha FROM graph_event_points p WHERE p.user_id=:uid",{'uid':uid})[0])
 assert points==state['points_before'],'正式要点或向量变化'
 report={'verified_at':datetime.now(ZoneInfo('Asia/Shanghai')).isoformat(),'database_readonly':True,'days':checks,'relations':sum(d['relations']for d in checks),'judgments':sum(d['archived_judgments']for d in checks),'evidence':sum(d['evidence']for d in checks),'points_unchanged':True,'points_digest':points,'model_calls':0}
 w.write_json(ROOT/'入库核验.json',report);print('ALL_VERIFIED',len(checks),report['relations'],report['judgments'],report['evidence'],flush=True)
