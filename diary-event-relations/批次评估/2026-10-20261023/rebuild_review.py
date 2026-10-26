"""新建受影响运行并复用来源逐字相同的既有判断；不篡改旧稿/旧包依赖。"""
import json,subprocess,sys,time
from pathlib import Path
from datetime import datetime,timezone
ROOT=Path(__file__).resolve().parent;PROJECT=ROOT.parents[2]
PYTHON=PROJECT/'backend/venv/bin/python';SCRIPT=PROJECT/'skills/diary-event-relations/scripts/workflow.py'
old=json.loads((ROOT/'运行清单.json').read_text()); corrections=json.loads((ROOT/'关系复核修正.json').read_text())
(ROOT/'运行清单-复核前.json').write_text(json.dumps(old,ensure_ascii=False,indent=2))
new=[];changes=[]
def call(args):
 start=time.monotonic();r=subprocess.run([str(PYTHON),str(SCRIPT),*map(str,args)],cwd=PROJECT/'backend',capture_output=True,text=True)
 if r.returncode:print(r.stdout,r.stderr);raise SystemExit(r.returncode)
 result=json.loads(r.stdout)
 with (ROOT/'工具记录.jsonl').open('a') as f:f.write(json.dumps({'at':datetime.now(timezone.utc).isoformat(),'command':args[0],'phase':'review_rebuild','elapsed_seconds':round(time.monotonic()-start,3),'exit_code':0,'result':result},ensure_ascii=False)+'\n')
 return result
for row in old:
 day=row['date'];of=Path(row['run_dir'])
 if day<'2026-10-09':new.append(row);continue
 args=['prepare','--username','x5456','--date',day,'--history-mode','replay']
 for dep in new:args+=['--completed-run',dep['run_dir']]
 prepared=call(args);nf=Path(prepared['run_dir']);os=json.loads((of/'source.json').read_text());ns=json.loads((nf/'source.json').read_text())
 assert os['events']==ns['events'] and os['pairs']==ns['pairs'] and os['recall']==ns['recall']
 results=json.loads((of/'results.json').read_text());results['package_sha256']=ns['package_sha256'];byid={r['pair_id']:r for r in results['results']}
 for pid,desc in corrections.get(day,{}).get('description_replace',[]):
  before=byid[pid]['relation']['description'];byid[pid]['relation']['description']=desc;byid[pid]['reason']=desc
  changes.append({'date':day,'pair_id':pid,'before':before,'after':desc,'reason':'来源只证实给父亲买酒，没有证实父亲已收到；删除过度陈述。'})
 for a,b,typ,desc,se,te in corrections.get(day,{}).get('add',[]):
  pair=next(p for p in ns['pairs'] if {p['event_a'],p['event_b']}=={a,b});r=byid[pair['pair_id']];assert r['status']=='NO_RELATION'
  def refs(alias,items):
   ev=[]
   for no,q in items:
    detail=next(x['detail'] for x in ns['events'][alias]['points'] if x['no']==no);assert detail.count(q)==1,(day,alias,no,q)
    prev=next((x for x in ev if x['point_no']==no),None)
    if prev:
     start=min(detail.index(prev['quote']),detail.index(q));end=max(detail.index(prev['quote'])+len(prev['quote']),detail.index(q)+len(q));prev['quote']=detail[start:end]
    else:ev.append({'point_no':no,'quote':q})
   return ev
  r.update(status='RELATED',reason=desc,relation={'source_event':a,'target_event':b,'relation_type':typ,'certainty':'EXPLICIT','description':desc,'source_evidence':refs(a,se),'target_evidence':refs(b,te)})
  changes.append({'date':day,'pair_id':pair['pair_id'],'before':'NO_RELATION','after':'RELATED','reason':desc})
 path=nf/'复核后逐对判断.json';path.write_text(json.dumps(results,ensure_ascii=False,indent=2))
 call(['record',nf,'--input',path]);status=call(['check',nf]);assert status['complete']
 call(['verify',nf]);call(['render',nf])
 (nf/'阅读留痕.json').write_text(json.dumps({'read_basis':'旧运行各批完整要点已读取，复核新来源事件、要点、候选、召回与旧包完全相同；仅依赖路径及来源包指纹改变。复用已有逐对语义判断并应用明确的复核修正。','original_run':str(of),'events_pairs_recall_exact_match':True},ensure_ascii=False,indent=2))
 new.append({'date':day,'run_dir':str(nf)});(ROOT/'运行清单.json').write_text(json.dumps(new,ensure_ascii=False,indent=2))
 print(json.dumps({'date':day,'counts':status['counts'],'new_run':str(nf)},ensure_ascii=False),flush=True)
(ROOT/'主代理关系复核记录.json').write_text(json.dumps({'completed_at':datetime.now(timezone.utc).isoformat(),'changes':changes,'reason':'汇总时复核全部正例及已读候选负例，纠正同一具体事项早期计划与后续执行的漏判；不因已有中间边而否认双方本身直接支持的关系。受依赖影响的日期全部重新prepare/check/verify/render，旧稿保留。'},ensure_ascii=False,indent=2))
