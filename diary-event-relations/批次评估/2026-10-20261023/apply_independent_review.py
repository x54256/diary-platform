"""根据主代理逐项核实的规格修改关系；新建回放依赖，完整保留当前主稿。"""
from pathlib import Path
from datetime import datetime,timezone
from zoneinfo import ZoneInfo
import json,sys,subprocess,hashlib,time,collections
ROOT=Path(__file__).resolve().parent;PROJECT=ROOT.parents[2]
SCRIPT=PROJECT/'skills/diary-event-relations/scripts/workflow.py';PYTHON=PROJECT/'backend/venv/bin/python'
sys.path.insert(0,str(SCRIPT.parent))
from draft import read_draft
stamp=datetime.now(ZoneInfo('Asia/Shanghai')).strftime('%Y%m%dT%H%M%S')
archive=ROOT/f'独立审核修订-{stamp}';archive.mkdir()
old=json.loads((ROOT/'运行清单.json').read_text());review=json.loads((ROOT/'独立关系审核.json').read_text());spec=json.loads((ROOT/'独立审核采纳规格.json').read_text())
assert set(spec)=={i['id'] for i in review['issues']}
(archive/'原运行清单.json').write_text(json.dumps(old,ensure_ascii=False,indent=2))
(archive/'采纳规格.json').write_text(json.dumps(spec,ensure_ascii=False,indent=2))
original={};byday=collections.defaultdict(list);decisions=[]
for run in old:
 folder=Path(run['run_dir']);source=json.loads((folder/'source.json').read_text());md,rows=read_draft(folder/'关系结果.md',source)
 original[run['date']]={'folder':folder,'source':source,'markdown':md,'rows':rows}
for issue in review['issues']:
 day=issue['events'][0]['date']
 # History-side event dates can differ from the current diary date: use package identity.
 day=json.loads((Path(issue['run_dir'])/'source.json').read_text())['diary_date']
 assert original[day]['folder']==Path(issue['run_dir'])
 byday[day].append(issue)
start_day=min(byday)
for day,obj in original.items():
 if day>=start_day:
  (archive/f'{day}-关系结果-修订前.md').write_text(obj['markdown'])
  (archive/f'{day}-当前主稿解析.json').write_text(json.dumps({'package_sha256':obj['source']['package_sha256'],'results':obj['rows']},ensure_ascii=False,indent=2))
new=[];audit=[]
def call(args):
 start=time.monotonic();p=subprocess.run([str(PYTHON),str(SCRIPT),*map(str,args)],cwd=PROJECT/'backend',capture_output=True,text=True)
 try:out=json.loads(p.stdout)
 except ValueError:out={'error':'CLI未返回JSON；原稿与输入已保留。','stdout':p.stdout,'stderr':p.stderr}
 record={'at':datetime.now(timezone.utc).isoformat(),'phase':'independent_review_accepted','command':args[0],'elapsed_seconds':round(time.monotonic()-start,3),'exit_code':p.returncode,'result':out}
 with (ROOT/'工具记录.jsonl').open('a') as f:f.write(json.dumps(record,ensure_ascii=False)+'\n')
 if p.returncode:print(json.dumps(out,ensure_ascii=False));raise SystemExit(p.returncode)
 return out
for oldrow in old:
 day=oldrow['date'];obj=original[day]
 if day<start_day:new.append(oldrow);continue
 args=['prepare','--username','x5456','--date',day,'--history-mode','replay']
 for dep in new:args+=['--completed-run',dep['run_dir']]
 prep=call(args);folder=Path(prep['run_dir']);s=json.loads((folder/'source.json').read_text())
 assert all(s[k]==obj['source'][k] for k in ['events','pairs','recall','config','embedding_model']), '来源/候选变化：必须重新语义核对，不能静默搬用旧结果。'
 # Authoritative input is current editable Markdown, never the potentially stale results cache.
 rows=json.loads(json.dumps(obj['rows'],ensure_ascii=False));byid={x['pair_id']:x for x in rows}
 for issue in byday[day]:
  iid=issue['id'];decision=spec[iid];row=byid[issue['pair_id']];before=json.loads(json.dumps(row,ensure_ascii=False))
  assert row['status']==issue['current_status'],(iid,'当前主稿状态已变化')
  if 'relation' in decision:
   r=decision['relation'];aliases={e['id']:a for a,e in s['events'].items()};a,b=aliases[r['source_id']],aliases[r['target_id']]
   pair=next(p for p in s['pairs'] if p['pair_id']==row['pair_id']);assert {a,b}=={pair['event_a'],pair['event_b']}
   def evidence(alias,refs):
    items=[]
    for no,quote in refs:
     detail=next(p['detail'] for p in s['events'][alias]['points'] if p['no']==no);assert detail.count(quote)==1,(iid,alias,no,quote)
     previous=next((x for x in items if x['point_no']==no),None)
     if previous:
      lo=min(detail.index(previous['quote']),detail.index(quote));hi=max(detail.index(previous['quote'])+len(previous['quote']),detail.index(quote)+len(quote));previous['quote']=detail[lo:hi]
     else:items.append({'point_no':no,'quote':quote})
    return items
   row.update(status='RELATED',reason=r['description'],relation={'source_event':a,'target_event':b,'relation_type':r['relation_type'],'certainty':r['certainty'],'description':r['description'],'source_evidence':evidence(a,r['source_evidence']),'target_evidence':evidence(b,r['target_evidence'])})
  else:
   assert row['status']=='RELATED'
   row['relation']['description']=decision['description'];row['reason']=decision['description']
  decisions.append({'issue_id':iid,'date':day,'pair_id':row['pair_id'],'decision':decision['decision'],'reason':decision['reason'],'before':before,'after':row,'source_file_sha256':hashlib.sha256((obj['folder']/'source.json').read_bytes()).hexdigest(),'old_run_dir':str(obj['folder']),'new_run_dir':str(folder)})
 result={'package_sha256':s['package_sha256'],'results':rows};path=folder/'独立审核采纳后逐对判断.json';path.write_text(json.dumps(result,ensure_ascii=False,indent=2))
 call(['record',folder,'--input',path]);checked=call(['check',folder]);assert checked['complete']
 verified=call(['verify',folder]);assert verified['verified_against_database']
 call(['render',folder])
 # Reparse new editable master and ensure parser preserves every authored decision.
 md,reparsed=read_draft(folder/'关系结果.md',s);assert reparsed==rows
 (folder/'修订来源说明.json').write_text(json.dumps({'review_report':str(ROOT/'独立关系审核.json'),'old_run_dir':str(obj['folder']),'read_basis':'主代理已重读所有建议涉及双方完整要点；新旧events/pairs/recall/config/model逐字相同；未受影响判断保留磁盘当前主稿解析结果。','applied_issue_ids':[i['id'] for i in byday[day]],'source_and_pair_content_unchanged':True},ensure_ascii=False,indent=2))
 new.append({'date':day,'run_dir':str(folder)});audit.append({'date':day,'old_run':str(obj['folder']),'new_run':str(folder),'counts':checked['counts'],'verified_at':verified['verified_at']})
 (archive/'新运行进度.json').write_text(json.dumps(new,ensure_ascii=False,indent=2))
 print(json.dumps({'date':day,'counts':checked['counts'],'changes':[i['id'] for i in byday[day]]},ensure_ascii=False),flush=True)
assert len(new)==len(old)==15 and len(decisions)==12
receipt={'completed_at':datetime.now(timezone.utc).isoformat(),'archive':str(archive),'accepted_confirmed_issues':11,'accepted_boundary_as_speculative':1,'added_relations':7,'description_corrections':5,'unresolved_preserved':2,'relation_database_written':False,'decisions':decisions,'runs':audit}
(archive/'执行回执.json').write_text(json.dumps(receipt,ensure_ascii=False,indent=2));(ROOT/'独立审核采纳记录.json').write_text(json.dumps(receipt,ensure_ascii=False,indent=2))
# Switch the current manifest only after the entire new dependency chain is complete and verified.
tmp=ROOT/'运行清单-待切换.json';tmp.write_text(json.dumps(new,ensure_ascii=False,indent=2));tmp.replace(ROOT/'运行清单.json')
print(json.dumps({'complete':True,'archive':str(archive),'accepted':12,'added_relations':7,'description_corrections':5},ensure_ascii=False),flush=True)
