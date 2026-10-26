"""本轮顺序驱动：不自动生成语义判断；新候选必须由主代理逐对给出。"""
from pathlib import Path
import json,sys,subprocess,time,copy,collections
from datetime import datetime,timezone
ROOT=Path(__file__).resolve().parent;PROJECT=ROOT.parents[2]
SCRIPT=PROJECT/'skills/diary-event-relations/scripts/workflow.py';PY=PROJECT/'backend/venv/bin/python'
sys.path.insert(0,str(SCRIPT.parent))
from draft import read_draft
from workflow import digest
INDEX=ROOT/'运行清单.json'
old=json.loads((PROJECT/'diary-event-relations/批次评估/2026-10-20261023/运行清单.json').read_text())
oldby={r['date']:Path(r['run_dir'])for r in old}
def write(p,v):Path(p).write_text(json.dumps(v,ensure_ascii=False,indent=2))
def call(args):
 t=time.monotonic();r=subprocess.run([str(PY),str(SCRIPT),*map(str,args)],cwd=PROJECT/'backend',capture_output=True,text=True)
 try:out=json.loads(r.stdout)
 except ValueError:out={'error':r.stderr.strip() if r.stderr.startswith('处理停止：') else 'CLI未返回JSON；详细输出不展示以免泄露连接信息','returncode':r.returncode}
 with (ROOT/'工具记录.jsonl').open('a')as f:f.write(json.dumps({'at':datetime.now(timezone.utc).isoformat(),'command':str(args[0]),'elapsed_seconds':round(time.monotonic()-t,3),'exit_code':r.returncode,'result':out if args[0]!='read' else {'batch':str(args[-1]),'saved_full_read_output':True}},ensure_ascii=False)+'\n')
 if r.returncode:print(json.dumps(out,ensure_ascii=False));raise SystemExit(r.returncode)
 return out
mode=sys.argv[1];runs=json.loads(INDEX.read_text())if INDEX.exists()else []
if mode=='prepare':
 day=sys.argv[2];prep=call(['prepare','--username','x5456','--date',day]);folder=Path(prep['run_dir']);s=json.loads((folder/'source.json').read_text())
 reuse=[];dropped=[];new=[];common=[];original=None
 if day in oldby:
  of=oldby[day];o=json.loads((of/'source.json').read_text());_,rows=read_draft(of/'关系结果.md',o);original={r['pair_id']:r for r in rows};aliases={e['id']:a for a,e in s['events'].items()}
  for pair in s['pairs']:
   if pair['pair_id']not in original:new.append(pair);continue
   op=next(p for p in o['pairs']if p['pair_id']==pair['pair_id'])
   for a in (op['event_a'],op['event_b']):
    oe=o['events'][a];ne=s['events'][aliases[oe['id']]]
    assert {k:v for k,v in oe.items()if k!='run_status'}=={k:v for k,v in ne.items()if k!='run_status'},'旧判断双方正式要点变化，需要重新判断'
   row=copy.deepcopy(original[pair['pair_id']]);rel=row['relation']
   if rel:
    for field in ('source_event','target_event'):rel[field]=aliases[o['events'][rel[field]]['id']]
   reuse.append(row);common.append(pair['pair_id'])
  dropped=[{'pair':p,'judgment':original[p['pair_id']],'events':{a:o['events'][a]for a in (p['event_a'],p['event_b'])}}for p in o['pairs']if p['pair_id']not in {p['pair_id']for p in s['pairs']}]
 else:new=s['pairs']
 write(folder/'旧稿核对后可复用判断.json',{'package_sha256':s['package_sha256'],'results':reuse})
 write(folder/'候选差异.json',{'date':day,'old_run':str(oldby.get(day,'')),'preserved':common,'new':new,'dropped':dropped,'reuse_basis':'已核验双方全部正式要点及向量指纹逐字相同，关系定义不变；以旧可编辑当前稿为准，按UUID重映射别名。','old_positive_dropped':sum(d['judgment']['status']=='RELATED'for d in dropped)})
 runs.append({'date':day,'run_dir':str(folder),'complete':False});write(INDEX,runs)
 # Read every formal batch and retain full output; show deduplicated sources for new semantic pairs.
 m=json.loads((folder/'run.json').read_text())
 for b in m['batches']:write(folder/(b['batch_id']+'-已读.json'),call(['read',folder,'--batch',b['batch_id']]))
 print(json.dumps({'date':day,'run_dir':str(folder),'history':{k:v for k,v in s['history_selection'].items()if k!='gaps'},'history_gap_count':len(s['history_selection']['gaps']),'history_dates':[h['diary_date']for h in s['history_inventory']if 'run_id'in h],'total_pairs':len(s['pairs']),'preserved':len(reuse),'new':len(new),'dropped':len(dropped),'old_positive_dropped':sum(d['judgment']['status']=='RELATED'for d in dropped)},ensure_ascii=False))
elif mode=='inspect':
 folder=Path(runs[-1]['run_dir']);s=json.loads((folder/'source.json').read_text());diff=json.loads((folder/'候选差异.json').read_text());needed={p[k]for p in diff['new']for k in ('event_a','event_b')}
 seen=json.loads((ROOT/'已读事件指纹.json').read_text())if (ROOT/'已读事件指纹.json').exists()else {}
 aliases=sorted(needed);start=int(sys.argv[2])if len(sys.argv)>2 else 0;stop=int(sys.argv[3])if len(sys.argv)>3 else len(aliases)
 print('SOURCE PAGE',start,stop,'TOTAL',len(aliases))
 for a in aliases[start:stop]:
  e=s['events'][a];key=digest(e)
  if seen.get(e['id'])!=key:
   print(a,e['diary_date'],e['title'])
   for p in e['points']:print(str(p['no'])+'. '+p['summary']+'\n'+p['detail'])
   seen[e['id']]=key
  else:print(a,e['diary_date'],e['title'],'（完整详情已读且指纹相同）')
 print('NEW PAIRS',','.join(p['event_a']+'-'+p['event_b']for p in diff['new']))
 write(ROOT/'已读事件指纹.json',seen)
elif mode=='record':
 folder=Path(runs[-1]['run_dir']);s=json.loads((folder/'source.json').read_text());diff=json.loads((folder/'候选差异.json').read_text());spec=json.load(sys.stdin);write(folder/'新候选判断规格.json',spec)
 rows=json.loads((folder/'旧稿核对后可复用判断.json').read_text())['results'];pairs={frozenset((p['event_a'],p['event_b'])):p for p in diff['new']};authored={}
 for a,b,typ,desc,se,te,*certain in spec.get('related',[]):
  pair=pairs[frozenset((a,b))]
  def evidence(alias,refs):
   out=[]
   for no,q in refs:
    detail=next(p['detail']for p in s['events'][alias]['points']if p['no']==no);assert detail.count(q)==1,(alias,no,q)
    prior=next((x for x in out if x['point_no']==no),None)
    if prior:
     lo=min(detail.index(prior['quote']),detail.index(q));hi=max(detail.index(prior['quote'])+len(prior['quote']),detail.index(q)+len(q));prior['quote']=detail[lo:hi]
    else:out.append({'point_no':no,'quote':q})
   return out
  authored[pair['pair_id']]={'pair_id':pair['pair_id'],'status':'RELATED','reason':desc,'relation':{'source_event':a,'target_event':b,'relation_type':typ,'certainty':certain[0]if certain else 'EXPLICIT','description':desc,'source_evidence':evidence(a,se),'target_evidence':evidence(b,te)}}
 for status,key in [('NO_RELATION','no_relation'),('UNRESOLVED','unresolved')]:
  for pairstr,reason in spec.get(key,[]):
   a,b=pairstr.split('-');pid=pairs[frozenset((a,b))]['pair_id'];assert pid not in authored
   authored[pid]={'pair_id':pid,'status':status,'reason':reason,'relation':None}
 assert len(authored)==len(pairs),(len(authored),len(pairs),[p for p in diff['new']if p['pair_id']not in authored])
 rows+=list(authored.values());byid={r['pair_id']:r for r in rows};rows=[byid[p['pair_id']]for p in s['pairs']]
 path=folder/'本轮完整逐对判断.json';write(path,{'package_sha256':s['package_sha256'],'results':rows});call(['record',folder,'--input',path]);check=call(['check',folder]);assert check['complete'];call(['verify',folder]);call(['render',folder]);runs[-1]['complete']=True;write(INDEX,runs);print(json.dumps({'date':s['diary_date'],'counts':check['counts'],'complete':True},ensure_ascii=False))
