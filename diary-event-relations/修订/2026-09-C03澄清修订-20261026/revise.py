import sys,json,shutil,hashlib
from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo
ROOT=Path(__file__).resolve().parent;PROJECT=ROOT.parents[2]
sys.path.insert(0,str(PROJECT/'skills/diary-event-relations/scripts'))
import workflow as w
from draft import read_draft,render_text
oldroot=PROJECT/'diary-event-relations/修订/2026-09-审阅采信修订-20261026'
state=w.read_json(oldroot/'execution.json');changes=[];runs=[]
spec={
 'P-1b0cd72ad8e4ac7e':('E024','E035',1,2,'在学完第二章并准备继续第三章后，进一步把同一心理学课程安排在中午或空闲时间学习；这是形成新时段安排，不表示该安排已经执行。'),
 'P-629f8909b7c68d08':('E009','E035',4,2,'此前重新开始普通心理学课程但尚未进入正轨，后来重新规划将同一课程放在中午或空闲时间学习，形成具体学习安排。'),
 'P-b485d2043e3e6a50':('E037','E042',2,1,'在形成中午或空闲学习该心理学课程的安排后，后来记录了视觉系统、视觉过程的继续学习及对不明白内容的梳理；不据此认定学习只发生在计划时段。')}
def proof(s,a,n):
 detail=next(p['detail']for p in s['events'][a]['points']if p['no']==n)
 if n==2 and s['events'][a]['title']=='规划每日学习与作息安排':quote=detail.split('，睡前')[0]
 elif s['events'][a]['title']=='刷老梁的视频，又陷入光看不做的状态':quote=detail.split('。')[0]+'。'
 elif s['events'][a]['title']=='继续学习视觉过程，也该把时间转回工作':quote=detail.split('\n\n')[0]
 else:quote=detail
 return [{'point_no':n,'quote':quote}]
for d in state['days']:
 if d['date']not in ['2026-09-20','2026-09-22']:continue
 folder=Path(d['run_dir']);s,_=w.load_package(folder);draft=folder/'关系结果.md';content,rows=read_draft(draft,s,complete=True)
 revised=[];daychanges=[]
 for row in rows:
  if row['pair_id']not in spec:revised.append(row);continue
  a,b,an,bn,desc=spec[row['pair_id']]
  after={'pair_id':row['pair_id'],'status':'RELATED','reason':desc,'relation':{'source_event':a,'target_event':b,'relation_type':'后续事件','certainty':'EXPLICIT','description':desc,'source_evidence':proof(s,a,an),'target_evidence':proof(s,b,bn)}}
  daychanges.append({'date':d['date'],'before':row,'after':after});revised.append(after)
 w.check_rows(s,{'package_sha256':s['package_sha256'],'results':revised})
 newtext=render_text(s,revised)
 backup=ROOT/(d['date']+'-修订前关系结果.md')
 if not backup.exists():backup.write_text(content)
 if content!=newtext:
  previous=folder/'关系结果-C03澄清前-20261026.md'
  if not previous.exists():previous.write_text(content)
  draft.write_text(newtext)
 _,actual=read_draft(draft,s,complete=True)
 prior={r['pair_id']:r for r in rows};changed={r['pair_id']for r in actual if r!=prior[r['pair_id']]}
 assert changed<set(spec)|{''} and changed=={c['before']['pair_id']for c in daychanges if c['before']!=c['after']}
 changes.extend(daychanges);runs.append({'date':d['date'],'run_dir':str(folder),'draft':str(draft),'before_sha256':hashlib.sha256(content.encode()).hexdigest(),'after_sha256':hashlib.sha256(newtext.encode()).hexdigest(),'relations':sum(r['status']=='RELATED'for r in actual),'unresolved':sum(r['status']=='UNRESOLVED'for r in actual)})
record='\n\n## C03 回答与采用（'+datetime.now(ZoneInfo('Asia/Shanghai')).isoformat()+'）\n\n用户原话：同一门普通心理学课程。\n\n该回答消除两种课程称呼的身份歧义；没有新增学习行动、时段或学习结果。双方原要点已分别记载重新开始、学完第二章、形成中午或空闲学习安排及后来继续学习视觉，三对逐对复核后均修订为后续事件。证据仍使用原要点，不把用户回答粘入quote，不修改正式要点或冻结来源。\n\n三对：P-1b0cd72ad8e4ac7e、P-629f8909b7c68d08、P-b485d2043e3e6a50。C03已解决，当前本批0对未决。当前稿已修改但尚未将该变化写入数据库；此前的整稿确认对应旧稿，本次新整稿待展示确认。\n'
for p in [oldroot/'澄清记录.md']+[Path(d['run_dir'])/'澄清记录.md'for d in runs]:
 with p.open('a')as f:f.write(record)
w.write_json(ROOT/'修改记录.json',changes);w.write_json(ROOT/'修订运行.json',runs)
print(json.dumps(runs,ensure_ascii=False))
