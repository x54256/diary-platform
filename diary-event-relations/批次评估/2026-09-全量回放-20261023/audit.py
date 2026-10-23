import sys,json,time
from datetime import datetime
from zoneinfo import ZoneInfo
from pathlib import Path
sys.path.insert(0,str(Path('skills/diary-event-relations/scripts').resolve()))
from db_source import connection,list_diaries,query,load_run
from workflow import WorkflowError
root=Path(__file__).parent
start=time.perf_counter()
rows=[]
with connection(Path('backend').resolve()) as conn:
    listing=list_diaries(conn,'x5456')
    listing['diaries']=[d for d in listing['diaries'] if str(d['diary_date']).startswith('2026-09-')]
    (root/'inventory.json').write_text(json.dumps(listing,ensure_ascii=False,indent=2,default=str))
    for d in listing['diaries']:
        t=time.perf_counter()
        row={'date':str(d['diary_date']),'diary_id':str(d['id']),'runs':len(d['runs'])}
        if len(d['runs'])!=1:
            row.update(status='BLOCKED',reason='没有正式事件要点运行' if not d['runs'] else '正式运行不唯一')
        else:
            rid=d['runs'][0]['id'];row['run_id']=str(rid)
            missing=query(conn,'''SELECT e.id,e.event_title,COALESCE(e.user_importance,e.ai_importance) importance
                FROM diary_events e JOIN diary_organized o ON e.diary_organized_id=o.id
                WHERE o.diary_id=:did AND NOT EXISTS (SELECT 1 FROM graph_run_events n WHERE n.run_id=:rid AND n.event_id=e.id)
                ORDER BY e.sort_order,e.id''',{'did':str(d['id']),'rid':str(rid)})
            row['missing_events']=[dict(m) for m in missing]
            try:
                events,_=load_run(conn,listing['user_id'],rid)
                row.update(status='READY',events=len(events),points=sum(len(e['points'])for e in events))
            except WorkflowError as exc: row.update(status='BLOCKED',reason=str(exc))
        row['audit_seconds']=round(time.perf_counter()-t,4);rows.append(row)
report={'audited_at':datetime.now(ZoneInfo('Asia/Shanghai')).isoformat(),'seconds':time.perf_counter()-start,'diaries':rows,'actual_host_tokens':None,'token_note':'宿主未提供实际 token 计量，不按字符估算费用','database_written':False}
(root/'coverage-audit.json').write_text(json.dumps(report,ensure_ascii=False,indent=2,default=str))
for r in rows:print(r['date'],r['diary_id'],r['status'],r.get('events'),r.get('points'),r.get('reason',''),len(r.get('missing_events',[])))
