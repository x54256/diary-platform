"""只读导出两个指定日记的正式要点及向量，不调用模型，不写数据库。"""
import hashlib
import json
import math
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[3]
OUT = Path(__file__).resolve().parent
os.chdir(ROOT / 'backend')
sys.path.insert(0, str(ROOT / 'backend'))
from database import SessionLocal
from sqlalchemy import text

USER = '2d7e382a-db46-45b3-b0c5-5c8ded2cc1f7'
DIARIES = ['828580fd-50a7-4a15-9d80-7acfe7ec987e', '085c0f45-8d1d-48ae-a2d3-b54da087adae']

def run():
    if (OUT/'source.json').exists():
        raise ValueError('已有冻结快照，重新实验须使用新目录')
    events, vectors, runs = [], {}, []
    with SessionLocal() as db:
        db.execute(text('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY'))
        for did in DIARIES:
            rows = db.execute(text("""SELECT r.id,r.diary_date,r.status,r.source_snapshot,r.source_sha256
                FROM graph_runs r JOIN diaries d ON d.id=r.diary_id
                WHERE r.user_id=CAST(:uid AS uuid) AND r.diary_id=CAST(:did AS uuid)
                  AND d.user_id=r.user_id AND d.deleted_at IS NULL
                  AND r.status IN ('POINTS_READY','PUBLISHED')
                ORDER BY r.created_at DESC,r.id DESC"""), {'uid':USER,'did':did}).mappings().all()
            if len(rows) != 1:
                raise ValueError('目标日记有效运行数量不是一，停止避免猜选')
            r = rows[0]
            source = r['source_snapshot']
            if isinstance(source,str): source=json.loads(source)
            runs.append({'id':str(r['id']),'diary_id':did,'diary_date':str(r['diary_date']),
                         'status':r['status'],'source_sha256':r['source_sha256']})
            nodes=db.execute(text("""SELECT n.event_id,n.source_order,n.occurred_on,e.event_title,e.body,
                     e.feeling,e.reflection,e.user_importance,e.ai_importance
                FROM graph_run_events n JOIN diary_events e ON e.id=n.event_id
                WHERE n.run_id=CAST(:rid AS uuid) AND n.user_id=CAST(:uid AS uuid)
                ORDER BY n.source_order,n.event_id"""),{'rid':str(r['id']),'uid':USER}).mappings().all()
            for n in nodes:
                points=db.execute(text("""SELECT id,no,summary,detail,embedding::text AS vector,embedding_model
                     FROM graph_event_points WHERE run_id=CAST(:rid AS uuid)
                     AND event_id=CAST(:eid AS uuid) AND user_id=CAST(:uid AS uuid) ORDER BY no"""),
                     {'rid':str(r['id']),'eid':str(n['event_id']),'uid':USER}).mappings().all()
                if not points: raise ValueError('事件缺少正式要点')
                original={}
                for e in source.get('events',[]):
                    if str(e.get('event_id'))==str(n['event_id']): original=e
                def arr(v):
                    if isinstance(v,str):v=json.loads(v)
                    if not isinstance(v,list):raise ValueError('正文不是数组')
                    return v
                event={'id':str(n['event_id']),'run_id':str(r['id']),'diary_date':str(r['diary_date']),
                    'occurred_on':str(n['occurred_on']) if n['occurred_on'] else None,
                    'title':n['event_title'],'source_order':n['source_order'],
                    'points':[{'id':str(p['id']),'no':p['no'],'summary':p['summary'],'detail':p['detail']} for p in points],
                    'source':original,'current_body':arr(n['body'])}
                events.append(event)
                for p in points:
                    v=json.loads(p['vector'])
                    if len(v)!=1024 or not all(math.isfinite(x) for x in v) or sum(x*x for x in v)==0:
                        raise ValueError('非法向量')
                    vectors[str(p['id'])]={'model':p['embedding_model'],'values':v}
    payload={'user_id':USER,'runs':runs,'events':events}
    raw=json.dumps(payload,ensure_ascii=False,indent=2)
    (OUT/'source.json').write_text(raw)
    (OUT/'vectors.json').write_text(json.dumps(vectors))
    (OUT/'snapshot-meta.json').write_text(json.dumps({'sha256':hashlib.sha256(raw.encode()).hexdigest(),
        'runs':runs,'events':len(events),'points':sum(len(e['points']) for e in events)},ensure_ascii=False,indent=2))
    print(json.dumps({'exported':True,'events':len(events),'points':sum(len(e['points']) for e in events)},ensure_ascii=False))

if __name__=='__main__':
    try:run()
    except Exception as exc:
        # 不输出数据库异常全文、连接串或认证信息。
        print(json.dumps({'exported':False,'error_type':type(exc).__name__},ensure_ascii=False))
        sys.exit(1)
