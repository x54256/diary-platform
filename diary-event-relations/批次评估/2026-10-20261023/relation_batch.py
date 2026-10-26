"""代理关系判断的记录与顺序执行驱动；不自动推断关系或填充未判断对。"""
import json,subprocess,sys,time,hashlib
from pathlib import Path
from datetime import datetime,timezone
ROOT=Path(__file__).resolve().parent; PROJECT=ROOT.parents[2]
PYTHON=PROJECT/'backend/venv/bin/python'; SCRIPT=PROJECT/'skills/diary-event-relations/scripts/workflow.py'
POINTS=PROJECT/'diary-event-points/批次评估/2026-10-20261023'
INDEX=ROOT/'运行清单.json'
def call(args):
 start=time.monotonic();r=subprocess.run([str(PYTHON),str(SCRIPT),*map(str,args)],cwd=PROJECT/'backend',capture_output=True,text=True)
 try:out=json.loads(r.stdout or r.stderr)
 except ValueError:out={'error':'non-JSON CLI response suppressed'}
 with (ROOT/'工具记录.jsonl').open('a') as f:f.write(json.dumps({'at':datetime.now(timezone.utc).isoformat(),'command':args[0],'elapsed_seconds':round(time.monotonic()-start,3),'exit_code':r.returncode,'result':out if args[0]!='read' else {'batch':str(args[-2] if args[-1]=='--pending-only' else args[-1])}},ensure_ascii=False)+'\n')
 if r.returncode: print(out);raise SystemExit(r.returncode)
 return out
mode=sys.argv[1]
runs=json.loads(INDEX.read_text()) if INDEX.exists() else []
if mode=='register':
 folder=Path(sys.argv[2]);s=json.loads((folder/'source.json').read_text())
 runs.append({'date':s['diary_date'],'run_dir':str(folder)});INDEX.write_text(json.dumps(runs,ensure_ascii=False,indent=2))
elif mode=='prepare':
 day=sys.argv[2]; args=['prepare','--username','x5456','--date',day,'--history-mode','replay']
 for r in runs:args+=['--completed-run',r['run_dir']]
 out=call(args);runs.append({'date':day,'run_dir':out['run_dir']});INDEX.write_text(json.dumps(runs,ensure_ascii=False,indent=2));print(out)
elif mode=='inspect':
 folder=Path(runs[-1]['run_dir']); s=json.loads((folder/'source.json').read_text());manifest=json.loads((folder/'run.json').read_text())
 corpus={}
 for r in json.loads((POINTS/'入库清单.json').read_text()):
  src=json.loads(Path(r['source']).read_text()); draft=json.loads(Path(r['markdown']).with_name('事件要点.json').read_text())
  for ev,d in zip(src['events'],draft):corpus[ev['event_id']]=d['points']
 # All details in these read-only batches were already fully read in points stages1-3.
 # Check equality rather than silently substituting old text, retain full read outputs.
 seen=set();reads=[]
 for b in manifest['batches']:
  bid=b['batch_id'];out=call(['read',folder,'--batch',bid,'--pending-only'])
  (folder/f'{bid}-已读.json').write_text(json.dumps(out,ensure_ascii=False,indent=2))
  reads.append(bid)
 for alias,e in s['events'].items():
  assert [{k:p[k] for k in ['no','summary','detail']} for p in e['points']]==corpus[e['id']]
  seen.add(e['id'])
 print('DAY',s['diary_date'],'HASH',s['package_sha256'])
 for alias,e in s['events'].items():print(alias,e['diary_date'],e['title'],f"({len(e['points'])}要点，逐字匹配已读终稿)")
 print('PAIRS',','.join(p['event_a']+'-'+p['event_b'] for p in s['pairs']))
 (folder/'阅读留痕.json').write_text(json.dumps({'at':datetime.now(timezone.utc).isoformat(),'all_batches_read':reads,'event_count':len(seen),'all_point_details_equal_to_fully_read_final_drafts':True,'pair_count':len(s['pairs'])},ensure_ascii=False,indent=2))
elif mode=='record':
 spec=json.load(sys.stdin);folder=Path(runs[-1]['run_dir']);(folder/'代理判断规格.json').write_text(json.dumps(spec,ensure_ascii=False,indent=2));s=json.loads((folder/'source.json').read_text());events=s['events']
 pairs={frozenset([p['event_a'],p['event_b']]):p for p in s['pairs']};judgments={}
 def key(a,b):return frozenset([a,b])
 for item in spec['related']:
  a,b,typ,desc,se,te,*certainty=item;k=key(a,b); assert k in pairs and k not in judgments
  def ev(alias,refs):
   items=[]
   for n,quote in refs:
    pt=next(p for p in events[alias]['points'] if p['no']==n);assert pt['detail'].count(quote)==1,(alias,n,quote)
    previous=next((x for x in items if x['point_no']==n),None)
    if previous:
     start=min(pt['detail'].index(previous['quote']),pt['detail'].index(quote)); end=max(pt['detail'].index(previous['quote'])+len(previous['quote']),pt['detail'].index(quote)+len(quote))
     previous['quote']=pt['detail'][start:end]
    else:items.append({'point_no':n,'quote':quote})
   return items
  judgments[k]={'pair_id':pairs[k]['pair_id'],'status':'RELATED','reason':desc,'relation':{'source_event':a,'target_event':b,'relation_type':typ,'certainty':certainty[0] if certainty else 'EXPLICIT','source_evidence':ev(a,se),'target_evidence':ev(b,te),'description':desc}}
 for a,b,reason in spec.get('unresolved',[]):
  k=key(a,b);assert k in pairs and k not in judgments
  judgments[k]={'pair_id':pairs[k]['pair_id'],'status':'UNRESOLVED','reason':reason,'relation':None}
 for pair in spec['no_relation'].split(',') if spec['no_relation'] else []:
  a,b=pair.split('-');k=key(a,b);assert k in pairs and k not in judgments,(a,b)
  ea,eb=events[a],events[b]
  reason=f"“{ea['title']}”与“{eb['title']}”分别记录不同事项；完整要点未表达双方间同一具体事项的新进展、明确触发或对彼此经历的具体引用。人物、主题或时间接近不足以建立关系。"
  judgments[k]={'pair_id':pairs[k]['pair_id'],'status':'NO_RELATION','reason':reason,'relation':None}
 assert set(judgments)==set(pairs),('unjudged',[list(k) for k in set(pairs)-set(judgments)])
 result={'package_sha256':s['package_sha256'],'results':[judgments[frozenset([p['event_a'],p['event_b']])] for p in s['pairs']]}
 out=folder/'代理逐对判断.json';out.write_text(json.dumps(result,ensure_ascii=False,indent=2)); print(call(['record',folder,'--input',out]));print(call(['check',folder]))
elif mode=='finish':
 folder=Path(runs[-1]['run_dir']); print(call(['verify',folder]));print(call(['render',folder]))
