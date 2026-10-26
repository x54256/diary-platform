import sys,json
from pathlib import Path
from types import SimpleNamespace
from datetime import datetime
from zoneinfo import ZoneInfo
ROOT=Path(__file__).resolve().parent;PROJECT=ROOT.parents[2]
sys.path.insert(0,str(PROJECT/'skills/diary-event-relations/scripts'))
import workflow as w
import storage as st
import db_source as db
runs=w.read_json(ROOT/'修订运行.json');result=[]
for d in runs:
 folder=Path(d['run_dir']);s,m=w.load_package(folder);rows=w.saved_results(folder,s);check=w.progress(s,rows,m);w.require(check['complete'],'稿件不完整')
 verified=db.verify(SimpleNamespace(run_dir=folder,backend_dir=PROJECT/'backend'));w.render(folder)
 packet=st.build_packet(folder,'x5456');st.validate_packet(packet)
 path=ROOT/(d['date']+'-入库包-'+packet['storage_sha256'][:16]+'.json')
 if not path.exists():w.write_json(path,packet)
 else:assert w.read_json(path)==packet
 with db.connection(PROJECT/'backend')as conn:
  preview=st.inspect_target(conn,packet,'x5456',replace_published=True,accept_published_revisions=True)
  _,_,archive=st.archive_for(conn,packet)
  stored_related=sum(r.get('status')=='RELATED'for r in archive['results'])
  stored_unresolved=sum(r.get('status')=='UNRESOLVED'for r in archive['results'])
 result.append({**d,'packet':str(path),'storage_sha256':packet['storage_sha256'],'source_verified':verified,'preflight':preview,'database_before':{'relations':stored_related,'unresolved':stored_unresolved},'database_written':False})
 print(d['date'],'READY',d['relations'],'old',stored_related,'unresolved_before',stored_unresolved,flush=True)
w.write_json(ROOT/'入库预检.json',{'at':datetime.now(ZoneInfo('Asia/Shanghai')).isoformat(),'days':result,'database_written':False})
