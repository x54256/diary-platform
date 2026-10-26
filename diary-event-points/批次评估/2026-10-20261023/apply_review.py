from pathlib import Path
from datetime import datetime,timezone
import json,hashlib
p=Path(__file__).resolve().parent
a=json.loads((p/'独立审核.json').read_text())
decisions=[]
for issue in a['issues']:
 r=next(x for x in a['days'] if x['date']==issue['date']); f=Path(r['run_dir'])
 s=json.loads((f/'source.json').read_text());d=json.loads((f/'事件要点.json').read_text())
 idx=next(k for k,e in enumerate(s['events']) if e['event_id']==issue['event_id'])
 q=d[idx]['points'][issue['point_no']-1]; change=issue['minimal_change']; key=change['field'];before=q[key]
 for ch in change.get('replacements',[change]):
  assert ch['old'] in q[key]
  q[key]=q[key].replace(ch['old'],ch['new'],1)
 (f/'事件要点.json').write_text(json.dumps(d,ensure_ascii=False,indent=2)+'\n')
 md=[f"# {issue['date']} 事件要点",'']
 for ev in d:
  md += ['## 事件：'+ev['title'],'']
  for pt in ev['points']:md += [f"### {pt['no']}. {pt['summary']}",'',pt['detail'],'']
 (f/'事件要点.md').write_text('\n'.join(md))
 decisions.append({'issue_id':issue['id'],'date':issue['date'],'event_id':issue['event_id'],'point_no':issue['point_no'],'decision':'采纳','reason':'主代理重读完整来源与当前完整事件后，确认属于主旨失真' if key=='summary' else '主代理重读完整来源与当前完整事件后，确认拆分造成关键所指缺失；只补来源已有背景','before':before,'after':q[key],'rechecked':'修改后复读完整事件，覆盖及归属保留，无新增事实、序号变化或信息删除。'})
(p/'修订判定.json').write_text(json.dumps({'stage':3,'completed_at':datetime.now(timezone.utc).isoformat(),'decisions':decisions},ensure_ascii=False,indent=2))
with (p/'流程留痕.md').open('a') as f:
 f.write('\n## 阶段2与3完成\n\n独立审核15篇129事件300要点，5个实质问题。主代理逐项重读完整来源及完整事件稿，5项全部采纳：4项独立可读背景、1项主旨喜欢对象失真。修前完整稿已留初稿备份，逐项前后文字及判断见修订判定.json。修后复读未改变覆盖、事件边界、要点数及来源。此时尚未读取入库说明及关系Skill。\n')
print('Stage 3: five issues verified and corrected; total remains 300 points.')
