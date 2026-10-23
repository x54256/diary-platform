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
state=load(statepath) if statepath.exists() else {'started_at':now(),'history_scope':'本次全部19篇已整理日记，按日期接续已完成运行；排除09-20未整理篇','actual_host_tokens':None,'database_written':False,'days':[],'commands':[]}
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
    assert all(d.get('complete') for d in state['days']), '前一日未完成，禁止提前准备'
    day=sys.argv[2]; audit=load(ROOT/'coverage-audit.json')['diaries'];row=next(r for r in audit if r['date']==day and r['status']=='READY')
    args=['prepare','--username','x5456','--diary-id',row['diary_id'],'--history-mode','replay']
    for prev in state['days']:
        if prev.get('complete'):args+=['--completed-run',prev['run_dir']]
    started=now();p=command(args);state['days'].append({'date':day,'diary_id':row['diary_id'],'run_dir':p['run_dir'],'started_at':started,'complete':False,'actual_host_tokens':None});save(statepath,state)
    print(json.dumps(p,ensure_ascii=False));status=command(['status',p['run_dir']]);print('batches',status['pending_batches'])
elif action=='show':
    d=state['days'][-1];folder=Path(d['run_dir']);source=load(folder/'source.json');manifest=load(folder/'run.json')
    cachepath=ROOT/'read-cache.json';cache=load(cachepath) if cachepath.exists() else {}
    if not d.get('all_batches_read'):
        for b in manifest['batches']:
            p=command(['read',folder,'--batch',b['batch_id'],'--pending-only'])
            d.setdefault('reads',[]).append({'batch':b['batch_id'],'at':now(),'input_chars':len(json.dumps(p,ensure_ascii=False,separators=(',',':')))})
        d['all_batches_read']=True;save(statepath,state)
    aliases={a:f"{e['diary_date'][5:]}#{e['source_order']}" for a,e in source['events'].items()}
    for a,e in source['events'].items():print(a,aliases[a],e['title'])
    fresh=[]
    for a,e in source['events'].items():
        identity=json.dumps(e,sort_keys=True,ensure_ascii=False)
        if cache.get(e['id'])!=identity:fresh.append((a,e));cache[e['id']]=identity
    # show 单次可输出的事件；分片完整阅读与共享缓存分开记录
    freshfile=ROOT/(d['date']+'-fresh.json')
    if not freshfile.exists():save(freshfile,{'events':fresh})
    else:fresh=load(freshfile)['events']
    start=int(sys.argv[2]) if len(sys.argv)>2 else 0
    end=int(sys.argv[3]) if len(sys.argv)>3 else len(fresh)
    for a,e in fresh[start:end]:
        print(a,'FULL',json.dumps([{'no':p['no'],'detail':p['detail']}for p in e['points']],ensure_ascii=False))
    save(cachepath,cache)
    print('FRESH',len(fresh),'SHOWN',start,end)
    for i,p in enumerate(source['pairs'],1):print(i,p['event_a'],p['event_b'])
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
