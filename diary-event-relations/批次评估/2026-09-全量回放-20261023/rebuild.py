"""已澄清的负例修订及依赖重建；只复用逐字段相同来源与候选的人工判断。"""
import importlib.util,json,time
from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo
ROOT=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location('runner',ROOT/'run.py')
# run.py 顶层无匹配动作只载入计量工具
import sys
sys.argv=['run.py','library'];runner=importlib.util.module_from_spec(spec);spec.loader.exec_module(runner)
state=runner.state;command=runner.command;save=runner.save;load=runner.load;now=runner.now
idx=next(i for i,d in enumerate(state['days'])if d['date']=='2026-09-09');day=state['days'][idx]
folder=Path(day['run_dir']);source=load(folder/'source.json')
sys.path.insert(0,str(ROOT.parents[2]/'skills/diary-event-relations/scripts'))
from draft import read_draft
_,rows=read_draft(folder/'关系结果.md',source,complete=True)
for n in (26,44):
 pid=source['pairs'][n-1]['pair_id'];r=next(r for r in rows if r['pair_id']==pid);assert r['status']=='UNRESOLVED'
 r.update(status='NO_RELATION',reason='两侧是不同的江西工作整理事项，原要点未定位同一次整理或同一具体问题的新进展；不能仅凭同项目建边。用户已澄清不是同一次整理。',relation=None)
packet=ROOT/'0909-澄清后判断.json';save(packet,{'package_sha256':source['package_sha256'],'results':rows})
with (folder/'澄清记录.md').open('a')as f:f.write('\n用户事实回答：“不同的事情，但是都是江西项目，不是同一次整理”。\n\n采用方式：两个候选均改为NO_RELATION，仅同项目不足以建边；没有新增正向关系或改写原要点。Q01已解决。当前整稿未确认入库。后续依赖按新结果重建。\n')
command(['record',folder,'--input',packet,'--replace'])
for action in ('check','verify','render'):command([action,folder])
day['clarification_resolved_at']=now()
oldlater=state['days'][idx+1:];state['days']=state['days'][:idx+1]
for d in oldlater:
 archived=dict(d);archived['abandoned_reason']='09-09澄清修订导致依赖结果指纹变化，重建同范围运行；旧语义判断仅在来源与候选逐字段相等后复用。';state.setdefault('abandoned_runs',[]).append(archived)
save(runner.statepath,state)
for old in oldlater:
 start=now();args=['prepare','--username','x5456','--diary-id',old['diary_id'],'--history-mode','replay']
 for prior in state['days']:args+=['--completed-run',prior['run_dir']]
 result=command(args);newfolder=Path(result['run_dir']);fresh=load(newfolder/'source.json');original=load(Path(old['run_dir'])/'source.json')
 for key in ('events','pairs','config','skill_sha256','recall'):assert fresh[key]==original[key],(old['date'],key)
 d={'date':old['date'],'diary_id':old['diary_id'],'run_dir':str(newfolder),'started_at':start,'complete':False,'actual_host_tokens':None,'replayed_from':old['run_dir'],'original_wall_seconds':old.get('wall_seconds'),'original_reads':old.get('reads',[]),'semantic_reuse_validated':True,'reuse_comparison_fields':['events','pairs','config','skill_sha256','recall']}
 state['days'].append(d);save(runner.statepath,state)
 manifest=load(newfolder/'run.json')
 for b in manifest['batches']:
  p=command(['read',newfolder,'--batch',b['batch_id'],'--pending-only']);d.setdefault('reads',[]).append({'batch':b['batch_id'],'at':now(),'input_chars':len(json.dumps(p,ensure_ascii=False,separators=(',',':'))),'semantic_reuse':True})
 d['all_batches_read']=True
 if old.get('complete'):
  _,priorrows=read_draft(Path(old['run_dir'])/'关系结果.md',original,complete=True)
  packet=ROOT/(old['date']+'-重建判断.json');save(packet,{'package_sha256':fresh['package_sha256'],'results':priorrows})
  command(['record',newfolder,'--input',packet])
  for action in ('check','verify','render'):command([action,newfolder])
  d.update(complete=True,ended_at=now());d['wall_seconds']=(datetime.fromisoformat(d['ended_at'])-datetime.fromisoformat(start)).total_seconds()
 else:
  assert old is oldlater[-1]
 d['rebuild_finished_at']=now();save(runner.statepath,state);print(old['date'],'rebuilt',d['complete'],flush=True)
