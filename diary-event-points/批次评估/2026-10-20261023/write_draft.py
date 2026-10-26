"""将代理逐事件判定的中心与详情保存；不自动生成语义内容。"""
import sys,json,hashlib
from pathlib import Path
from datetime import datetime,timezone
ROOT=Path(__file__).resolve().parent
spec=json.load(sys.stdin)
day=spec['date']
runs=list((ROOT.parents[1]/day).glob('*/*/source.json'))
p=max(runs,key=lambda p:p.stat().st_mtime)
s=json.loads(p.read_text())
assert len(spec['events'])==len(s['events'])
out=[]; md=[f'# {day} 事件要点','']
for event,points in zip(s['events'],spec['events']):
 result=[]; covered=[]
 md += ['## 事件：'+event['title'],'']
 for n,item in enumerate(points,1):
  summary=item[0]; indexes=item[1]; detail=item[2] if len(item)>2 else '\n\n'.join(event['body'][i-1] for i in indexes)
  covered+=indexes
  result.append({'no':n,'summary':summary,'detail':detail})
  md += [f'### {n}. {summary}','',detail,'']
 assert set(covered)==set(range(1,len(event['body'])+1)),(event['title'],covered)
 out.append({'title':event['title'],'points':result})
p.parent.joinpath('事件要点.md').write_text('\n'.join(md))
p.parent.joinpath('事件要点.json').write_text(json.dumps(out,ensure_ascii=False,indent=2)+'\n')
record={'stage':1,'date':day,'completed_at':datetime.now(timezone.utc).isoformat(),'run_dir':str(p.parent),'source_sha256':s['source_sha256'],'events':len(out),'points':sum(len(e['points']) for e in out),'draft_sha256':hashlib.sha256(p.parent.joinpath('事件要点.md').read_bytes()).hexdigest(),'self_check':'逐事件核对正文/感受/反思覆盖、归属与不确定性；已有自然完整表述可沿用，按中心合并，不设固定数量。'}
with ROOT.joinpath('逐日记录.jsonl').open('a') as f:f.write(json.dumps(record,ensure_ascii=False)+'\n')
print(json.dumps(record,ensure_ascii=False))
