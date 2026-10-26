from pathlib import Path
import json,sys,collections,hashlib
from datetime import datetime,timezone
ROOT=Path(__file__).resolve().parent;PROJECT=ROOT.parents[2]
sys.path.insert(0,str(PROJECT/'skills/diary-event-relations/scripts'))
from workflow import load_package,saved_results,progress,digest
from draft import read_draft
from storage import resolve
runs=json.loads((ROOT/'运行清单.json').read_text());assert len(runs)==16 and all(r['complete']for r in runs)
old=json.loads((PROJECT/'diary-event-relations/批次评估/2026-10-20261023/运行清单.json').read_text())
summary=[];relations=[];cross=[];dropped=[];retainedreview=[];judgednew=0;preserved=0;recallpairs=0;sameday=0
index=['# 9月30日补稿与十月跨月关系稿索引','','本次统一从数据库召回所有较早的有效正式要点；包含九月及八月17、18日的已有要点，不以本地关系稿或发布状态限定历史。阈值0.4、事件级统一Top 5；同日完整两两比较。关系仅本地稿，未发布。','','| 日期 | 历史有效运行 | 候选 | 保留旧判断 | 新判断 | 关系 | 无关系 | 未决 | 完整稿 |','| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |']
for item in runs:
 f=Path(item['run_dir']);s,m=load_package(f);text,rows=read_draft(f/'关系结果.md',s);state=progress(s,rows,m);assert state['complete'];diff=json.loads((f/'候选差异.json').read_text());resolved=resolve(s,rows)
 positives=[r for r in rows if r['status']=='RELATED'];judgednew+=len(diff['new']);preserved+=len(diff['preserved'])
 for p in s['pairs']:
  a,b=[s['events'][p[k]]for k in ['event_a','event_b']]
  if a['diary_date']==b['diary_date']:sameday+=1
  else:recallpairs+=1
 for r in positives:
  rel=r['relation'];a,b=s['events'][rel['source_event']],s['events'][rel['target_event']]
  record={'current_date':item['date'],'pair_id':r['pair_id'],'source':a,'target':b,'relation':rel,'run_dir':str(f),'is_new_candidate':r['pair_id']in{p['pair_id']for p in diff['new']}}
  relations.append(record)
  if a['diary_date'][:7]!=b['diary_date'][:7]:cross.append(record)
 for d in diff['dropped']:
  if d['judgment']['status']=='RELATED':dropped.append({'current_date':item['date'],'old_run_dir':diff['old_run'],**d})
 counts=state['counts'];summary.append({'date':item['date'],'run_dir':str(f),'pairs':len(rows),'preserved':len(diff['preserved']),'new':len(diff['new']),'dropped':len(diff['dropped']),'old_positive_dropped':diff['old_positive_dropped'],'counts':counts,'history_selection':s['history_selection'],'source_package_sha256':s['package_sha256'],'database_verification':json.loads((f/'verification.json').read_text())})
 index.append(f"| {item['date']} | {s['history_selection']['run_count']} | {len(rows)} | {len(diff['preserved'])} | {len(diff['new'])} | {counts.get('RELATED',0)} | {counts.get('NO_RELATION',0)} | {counts.get('UNRESOLVED',0)} | [关系稿](<{f/'关系结果.md'}>) |")
# Old reviewed positives retained by UUID and exact semantic JSON, allowing aliases to change.
for olditem in old:
 of=Path(olditem['run_dir']);o=json.loads((of/'source.json').read_text());_,oldrows=read_draft(of/'关系结果.md',o)
 f=Path(next(r['run_dir']for r in runs if r['date']==olditem['date']));s=json.loads((f/'source.json').read_text());_,newrows=read_draft(f/'关系结果.md',s);byid={r['pair_id']:r for r in newrows}
 for row in oldrows:
  if row['status']!='RELATED':continue
  if row['pair_id']not in byid:continue
  def canonical(snapshot,row):
   r=json.loads(json.dumps(row));rel=r['relation']
   if rel:
    for key in ['source_event','target_event']:rel[key]=snapshot['events'][rel[key]]['id']
   return r
  assert canonical(o,row)==canonical(s,byid[row['pair_id']]),'既有审核正例被意外改动'
  retainedreview.append({'date':olditem['date'],'pair_id':row['pair_id']})
write=lambda p,v:Path(p).write_text(json.dumps(v,ensure_ascii=False,indent=2))
write(ROOT/'逐日汇总.json',summary);write(ROOT/'当前关系.json',relations);write(ROOT/'跨月关系.json',cross);write(ROOT/'旧正例退出候选.json',dropped);write(ROOT/'旧正例保真核验.json',retainedreview)
(ROOT/'关系稿索引.md').write_text('\n'.join(index)+'\n')
def readable(records,title):
 out=['# '+title,'']
 for i,r in enumerate(records,1):
  rel=r['relation'];out += [f"## {i}. {r['source']['diary_date']}｜{r['source']['title']} → {r['target']['diary_date']}｜{r['target']['title']}",'',f"类型：{rel['relation_type']}；确定性：{rel['certainty']}",'',rel['description'],'']
  for side,ev in [('source',r['source']),('target',r['target'])]:
   out+=['### '+('来源'if side=='source'else'目标')+'证据','']
   for ref in rel[side+'_evidence']:
    out += [f"要点 {ref['point_no']}",'', '> '+ref['quote'].replace('\n','\n> '),'']
  out += [f"[当前完整稿](<{Path(r['run_dir'])/'关系结果.md'}>)",'']
 return '\n'.join(out)
(ROOT/'跨月关系稿.md').write_text(readable(cross,'跨月事件关系稿'))
(ROOT/'当前关系总览.md').write_text(readable(relations,'9月30日与十月当前关系总览'))
oldrecords=[]
for r in dropped:
 rel=r['judgment']['relation'];oldrecords.append({'source':r['events'][rel['source_event']],'target':r['events'][rel['target_event']],'relation':rel,'run_dir':r['old_run_dir']})
(ROOT/'旧正例退出候选对照.md').write_text('本表保留此前已经识别的关系及原证据。本轮因全历史统一Top 5而未进入候选，未重新判成无关系；不计入本轮冻结候选的关系数。\n\n'+readable(oldrecords,'退出新候选的旧正例'))
metrics={'completed_at':datetime.now(timezone.utc).isoformat(),'runs':len(runs),'pairs':sum(r['pairs']for r in summary),'same_day_pairs':sameday,'history_pairs':recallpairs,'preserved_judgments':preserved,'newly_judged_pairs':judgednew,'relations':len(relations),'cross_month_relations':len(cross),'september_to_october_relations':sum({r['source']['diary_date'][:7],r['target']['diary_date'][:7]}=={'2026-09','2026-10'}for r in cross),'old_positive_preserved':len(retainedreview),'old_positive_dropped':len(dropped),'counts':dict(collections.Counter(r['status']for item in runs for r in read_draft(Path(item['run_dir'])/'关系结果.md',json.loads((Path(item['run_dir'])/'source.json').read_text()))[1])),'database_relations_written':False,'host_tokens':None,'host_cost':None}
write(ROOT/'完成指标.json',metrics)
print(json.dumps(metrics,ensure_ascii=False,indent=2))
