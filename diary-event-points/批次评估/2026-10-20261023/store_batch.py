"""串行调用Skill正式命令，保存脱敏结果及耗时，失败即停。"""
import json,subprocess,sys,time
from pathlib import Path
from datetime import datetime,timezone
ROOT=Path(__file__).resolve().parent
PROJECT=ROOT.parents[2]
SCRIPT=PROJECT/'skills/diary-event-points/scripts/store_points.py'
PYTHON=PROJECT/'backend/venv/bin/python'
mode=sys.argv[1]
rows=json.loads((ROOT/'入库清单.json').read_text())
for r in rows:
 f=Path(r['output']);start=time.monotonic()
 if mode=='prepare':args=['prepare','--source',r['source'],'--markdown',r['markdown'],'--output',r['output']]
 elif mode=='save':
  packet=json.loads(f.read_text());args=['save',str(f),'--write','--confirmed-sha256',packet['confirmation_sha256']]
 elif mode=='status':args=['status',str(f)]
 else:raise SystemExit('unknown mode')
 result=subprocess.run([str(PYTHON),str(SCRIPT),*args],cwd=PROJECT/'backend',capture_output=True,text=True)
 record={'stage':4,'command':mode,'date':r['date'],'at':datetime.now(timezone.utc).isoformat(),'elapsed_seconds':round(time.monotonic()-start,3),'exit_code':result.returncode}
 try:record['result']=json.loads(result.stdout or result.stderr)
 except ValueError:record['result']={'error':'CLI non-JSON output suppressed; inspect local execution environment'}
 (f.parent/f'{mode}-结果.json').write_text(json.dumps(record,ensure_ascii=False,indent=2))
 with (ROOT/'入库执行记录.jsonl').open('a') as out:out.write(json.dumps(record,ensure_ascii=False)+'\n')
 print(json.dumps(record,ensure_ascii=False),flush=True)
 if result.returncode:raise SystemExit(result.returncode)
 if mode in ['save','status'] and record['result'].get('stored') is not True:raise SystemExit('stored != true')
