import sys,json,time,subprocess
from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo
ROOT=Path(__file__).resolve().parent
PROJECT=ROOT.parents[2]
PYTHON=PROJECT/'backend/venv/bin/python'
FLOW=PROJECT/'skills/diary-event-relations/scripts/workflow.py'
def now():return datetime.now(ZoneInfo('Asia/Shanghai')).isoformat()
def load(p):return json.loads(p.read_text())
def save(p,v):p.write_text(json.dumps(v,ensure_ascii=False,indent=2)+'\n')
statepath=ROOT/'execution.json'
state=load(statepath) if statepath.exists() else {'started_at':now(),'history_scope':'仅本次来源完整并完成的较早日期；有缺失日期，非完整九月历史','actual_host_tokens':None,'database_written':False,'days':[],'commands':[]}
def command(args):
    t=time.perf_counter();started=now()
    r=subprocess.run([str(PYTHON),str(FLOW),*map(str,args)],cwd=PROJECT,capture_output=True,text=True)
    index=len(state['commands'])+1
    log=ROOT/f'command-{index:03}.json'
    item={'args':list(map(str,args)),'started_at':started,'ended_at':now(),'seconds':time.perf_counter()-t,'exit_code':r.returncode,'stdout':r.stdout,'stderr':r.stderr}
    save(log,item);state['commands'].append({'log':str(log),'seconds':item['seconds'],'exit_code':r.returncode});save(statepath,state)
    if r.returncode:print(r.stderr);sys.exit(r.returncode)
    return json.loads(r.stdout)
action=sys.argv[1]
if action=='prepare':
    day=sys.argv[2]; audit=load(ROOT/'coverage-audit.json')['diaries'];row=next(r for r in audit if r['date']==day and r['status']=='READY')
    args=['prepare','--username','x5456','--diary-id',row['diary_id'],'--history-mode','replay']
    for prev in state['days']:
        if prev.get('complete'):args+=['--completed-run',prev['run_dir']]
    started=now();p=command(args);state['days'].append({'date':day,'diary_id':row['diary_id'],'run_dir':p['run_dir'],'started_at':started,'complete':False,'actual_host_tokens':None});save(statepath,state)
    print(json.dumps(p,ensure_ascii=False));print(json.dumps(command(['status',p['run_dir']]),ensure_ascii=False))
elif action=='readunique':
    d=state['days'][-1];seen=set(d.get('shown_events',[]))
    for batch in sys.argv[2:]:
        p=command(['read',d['run_dir'],'--batch',batch,'--pending-only'])
        d.setdefault('reads',[]).append({'batch':batch,'at':now(),'input_chars':len(json.dumps(p,ensure_ascii=False,separators=(',',':')))})
        fresh=[e for e in p['events'] if e['id'] not in seen];seen.update(e['id'] for e in fresh)
        p['events']=fresh;print(json.dumps(p,ensure_ascii=False,separators=(',',':')))
        d['shown_events']=sorted(seen);save(statepath,state)
elif action=='read':
    d=state['days'][-1];batch=sys.argv[2];p=command(['read',d['run_dir'],'--batch',batch,'--pending-only']);print(json.dumps(p,ensure_ascii=False,separators=(',',':')))
    d.setdefault('reads',[]).append({'batch':batch,'at':now(),'input_chars':len(json.dumps(p,ensure_ascii=False,separators=(',',':')))});save(statepath,state)
elif action=='review':
    d=state['days'][-1];d['review_started_at']=now()
    for cmd in ['check','verify','render']:print(json.dumps(command([cmd,d['run_dir']]),ensure_ascii=False))
    d['review_ended_at']=now();save(statepath,state)
elif action=='finish':
    d=state['days'][-1];folder=Path(d['run_dir']);print(json.dumps(command(['record',folder,'--input',ROOT/(d['date']+'-decisions.json')]),ensure_ascii=False))
    for cmd in ['check','verify','render']:print(json.dumps(command([cmd,folder]),ensure_ascii=False))
    d['complete']=True;d['ended_at']=now();d['wall_seconds']=(datetime.fromisoformat(d['ended_at'])-datetime.fromisoformat(d['started_at'])).total_seconds();save(statepath,state)
