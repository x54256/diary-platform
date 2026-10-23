import importlib.util,json,sys
from pathlib import Path
from datetime import datetime
ROOT=Path(__file__).resolve().parent
sys.argv=['run.py','library'];spec=importlib.util.spec_from_file_location('runner',ROOT/'run.py');runner=importlib.util.module_from_spec(spec);spec.loader.exec_module(runner)
state=runner.state;command=runner.command;save=runner.save;load=runner.load;now=runner.now
sys.path.insert(0,str(ROOT.parents[2]/'skills/diary-event-relations/scripts'))
from draft import read_draft
staged=[]
for d in state['days']:
 s=load(Path(d['run_dir'])/'source.json');_,rows=read_draft(Path(d['run_dir'])/'关系结果.md',s,complete=True);staged.append((dict(d),s,rows))
reviewlog=[]
for d,s,rows in staged:
 day=d['date']
 def row(n):return next(r for r in rows if r['pair_id']==s['pairs'][n-1]['pair_id'])
 def ev(a,n,quote=None):
  p=next(p for p in s['events'][a]['points']if p['no']==n)
  if quote is None:quote=p['detail']
  assert p['detail'].count(quote)==1
  return {'point_no':n,'quote':quote}
 def patch(n,side,values):
  row(n)['relation'][side+'_evidence']=values;reviewlog.append({'date':day,'pair_no':n,'change':'补足连续短引，确保主体、事项、行动和描述可由所选证据支持','side':side})
 if day=='2026-09-12':
  patch(43,'source',[ev('E010',1,'我的脚很脏，还放到了她的枕头上'),ev('E010',3,next(p['detail']for p in s['events']['E010']['points']if p['no']==3).split('\n\n')[0])])
 if day=='2026-09-15':patch(17,'target',[ev('E029',1)])
 if day=='2026-09-19':patch(10,'source',[ev('E013',1),ev('E013',2,'YouTube 也要限时，不能全天一直看视频')])
 if day=='2026-09-20':
  patch(4,'target',[ev('E029',1)]);patch(9,'target',[ev('E025',3)])
 if day=='2026-09-22':
  for n in (5,8):patch(n,'target',[ev('E030',1)])
  patch(6,'source',[ev('E030',1)]);patch(6,'target',[ev('E031',2)])
  patch(32,'source',[ev('E001',1)])
  for n in (33,42):patch(n,'target',[ev('E032',3)])
  patch(35,'target',[ev('E031',2)])
  patch(50,'target',[ev('E033',1,'昨天早上继续看视觉系统、视觉过程'),ev('E033',2,'明天不能再看心理学')])
 if day=='2026-09-23':
  patch(7,'source',[ev('E016',2)]);patch(17,'source',[ev('E009',1,next(p['detail']for p in s['events']['E009']['points']if p['no']==1))])
 if day=='2026-09-25':
  patch(12,'target',[ev('E039',1)])
  detail=next(p['detail']for p in s['events']['E022']['points']if p['no']==2);patch(14,'source',[ev('E022',2,detail[detail.index('我说刘佳医生'):])])
  patch(54,'target',[ev('E050',1)])
  detail=next(p['detail']for p in s['events']['E046']['points']if p['no']==1);patch(74,'source',[ev('E046',1,detail.split('\n\n')[0])])
  patch(85,'source',[ev('E034',3)]);patch(87,'source',[ev('E047',2)]);patch(118,'source',[ev('E035',2)])
  r=row(126);assert r['status']=='UNRESOLVED';r.update(status='RELATED',reason='两侧均有七百多餐费和准备转钱给颂梅的事实，菜系原文均不确定；用户确认同一顿饭，仅消歧原文指代。',relation={'source_event':'E048','target_event':'E015','relation_type':'提及事件','certainty':'EXPLICIT','source_evidence':[ev('E048',2,'还有一次吃贵阳菜还是什么，花了不少，我该给她七百饭钱还未转，准备一会回去转。')],'target_evidence':[ev('E015',2)],'description':'盘点近期消费时，回顾此前带哒哒去餐厅吃的七百多元那顿饭，并记录当时仍未转给颂梅的餐费。'})
  with (Path(d['run_dir'])/'澄清记录.md').open('a')as f:f.write('\n用户回答：“是同一顿饭”。\n\n采用方式：两侧已有七百多餐费、拟转给颂梅及不确定菜系，回答仅消歧，改为盘点消费条目提及旧饭局。未新增饭局或声称已经转钱。Q02已解决，无待回答问题。\n')
  reviewlog.append({'date':day,'pair_no':126,'change':'按用户明确消歧改为RELATED／提及事件，保留未转款状态'})
 if day=='2026-09-27':
  patch(7,'source',[ev('E028',1,'一点多带多多、哒哒出发去清远酒店。')]);patch(38,'source',[ev('E027',2)]);patch(48,'source',[ev('E020',3)])
 if day=='2026-09-29':patch(28,'source',[ev('E005',2,'第一步，根据每天日记整理出的事件，纯人工、没有系统参与地建立联系、画图谱，弄清事件、人物、经验、思考等实体，以及关系和关系类型。')])
 save(ROOT/(day+'-终核判断.json'),{'package_sha256':s['package_sha256'],'results':rows})
save(ROOT/'终核修订记录.json',reviewlog)
idx=next(i for i,d in enumerate(state['days'])if d['date']=='2026-09-12')
first,s,rows=staged[idx];folder=Path(first['run_dir']);command(['record',folder,'--input',ROOT/(first['date']+'-终核判断.json'),'--replace'])
for action in ('check','verify','render'):command([action,folder])
state['days'][idx]['final_review_at']=now()
oldlater=staged[idx+1:];state['days']=state['days'][:idx+1]
for old,_,_ in oldlater:
 archive=dict(old);archive['abandoned_reason']='最终证据完整性核对与09-25餐费消歧后，依赖指纹更新；保留旧版并按同源同候选重建。';archive['superseded_at']=now();state.setdefault('abandoned_runs',[]).append(archive)
save(runner.statepath,state)
for old,original,rows in oldlater:
 started=now();args=['prepare','--username','x5456','--diary-id',old['diary_id'],'--history-mode','replay']
 for prior in state['days']:args+=['--completed-run',prior['run_dir']]
 result=command(args);folder=Path(result['run_dir']);s=load(folder/'source.json')
 for key in ('events','pairs','config','skill_sha256','recall'):assert s[key]==original[key],(old['date'],key)
 d={'date':old['date'],'diary_id':old['diary_id'],'run_dir':str(folder),'started_at':started,'complete':False,'actual_host_tokens':None,'replayed_from':old['run_dir'],'original_wall_seconds':old.get('original_wall_seconds')or old.get('wall_seconds'),'original_reads':old.get('original_reads')or old.get('reads',[]),'semantic_reuse_validated':True,'reuse_comparison_fields':['events','pairs','config','skill_sha256','recall'],'final_review_rebuild':True}
 state['days'].append(d);save(runner.statepath,state)
 for b in load(folder/'run.json')['batches']:
  p=command(['read',folder,'--batch',b['batch_id'],'--pending-only']);d.setdefault('reads',[]).append({'batch':b['batch_id'],'at':now(),'input_chars':len(json.dumps(p,ensure_ascii=False,separators=(',',':'))),'semantic_reuse':True})
 packet=ROOT/(old['date']+'-最终包判断.json');save(packet,{'package_sha256':s['package_sha256'],'results':rows});command(['record',folder,'--input',packet])
 for action in ('check','verify','render'):command([action,folder])
 for name in ('澄清记录.md',):
  prior=Path(old['run_dir'])/name
  if prior.exists():(folder/name).write_text(prior.read_text())
 d.update(all_batches_read=True,complete=True,ended_at=now());d['wall_seconds']=(datetime.fromisoformat(d['ended_at'])-datetime.fromisoformat(started)).total_seconds();save(runner.statepath,state)
 print(old['date'],'final checked',len(rows),flush=True)
state['finished_identification_at']=now();save(runner.statepath,state)
